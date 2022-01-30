#!/usr/bin/env python3

"""converts various chat formats into the chat_downloader format"""

import json
from .util import debug, info, warn, error


def convert_file(f):
    from chat_downloader.sites.youtube import YouTubeChatDownloader as CDY
    from chat_downloader.utils.core import (
        multi_get,
        try_get_first_key,
        remove_prefixes,
        remove_suffixes,
        camel_case_split,
    )

    try:
        lineno = 0
        info("converting from yt-dlp format...")
        f.seek(0, 2)
        filesz = f.tell()
        f.seek(0)
        for ln in f:
            lineno += 1
            if lineno % 10000 == 0:
                info(
                    f"converting line {lineno:,} (about {(f.tell() * 100.0 / filesz):.0f}% done)"
                )

            if not ln:
                continue

            # values required by chat_downloader's translator:
            offset = 0  # only relevant for clips (provided in initial_info)
            action = json.loads(ln)

            # all the remaining code was copied (with slight modifications) from
            # https://github.com/xenova/chat-downloader/blob/v0.1.10/chat_downloader/sites/youtube.py#L1693
            data = {}

            # if it is a replay chat item action, must re-base it
            replay_chat_item_action = action.get("replayChatItemAction")
            if replay_chat_item_action:
                offset_time = replay_chat_item_action.get("videoOffsetTimeMsec")
                if offset_time and offset_time != "isLive":
                    data["time_in_seconds"] = float(offset_time) / 1000

                action = replay_chat_item_action["actions"][0]

            action.pop("clickTrackingParams", None)
            original_action_type = try_get_first_key(action)

            data["action_type"] = camel_case_split(
                remove_suffixes(original_action_type, ("Action", "Command"))
            )

            original_message_type = None
            original_item = {}

            # We now parse the info and get the message
            # type based on the type of action
            if original_action_type in CDY._KNOWN_ITEM_ACTION_TYPES:
                original_item = multi_get(action, original_action_type, "item")

                original_message_type = try_get_first_key(original_item)
                data = CDY._parse_item(original_item, data, offset)

            elif original_action_type in CDY._KNOWN_REMOVE_ACTION_TYPES:
                original_item = action
                if original_action_type == "markChatItemAsDeletedAction":
                    original_message_type = "deletedMessage"
                else:  # markChatItemsByAuthorAsDeletedAction
                    original_message_type = "banUser"

                data = CDY._parse_item(original_item, data, offset)

            elif original_action_type in CDY._KNOWN_REPLACE_ACTION_TYPES:
                original_item = multi_get(
                    action, original_action_type, "replacementItem"
                )

                original_message_type = try_get_first_key(original_item)
                data = CDY._parse_item(original_item, data, offset)

            elif original_action_type in CDY._KNOWN_TOOLTIP_ACTION_TYPES:
                original_item = multi_get(action, original_action_type, "tooltip")

                original_message_type = try_get_first_key(original_item)
                data = CDY._parse_item(original_item, data, offset)

            elif original_action_type in CDY._KNOWN_ADD_BANNER_TYPES:
                original_item = multi_get(
                    action, original_action_type, "bannerRenderer"
                )

                if original_item:
                    original_message_type = try_get_first_key(original_item)

                    header = original_item[original_message_type].get("header")
                    parsed_header = CDY._parse_item(header, offset=offset)
                    header_message = parsed_header.get("message")

                    contents = original_item[original_message_type].get("contents")
                    parsed_contents = CDY._parse_item(contents, offset=offset)

                    data.update(parsed_header)
                    data.update(parsed_contents)
                    data["header_message"] = header_message
                else:
                    debug(
                        "No bannerRenderer item",
                        f"Action type: {original_action_type}",
                        f"Action: {action}",
                        f"Parsed data: {data}",
                    )

            elif original_action_type in CDY._KNOWN_REMOVE_BANNER_TYPES:
                original_item = action
                original_message_type = "removeBanner"
                data = CDY._parse_item(original_item, data, offset)

            elif original_action_type in CDY._KNOWN_IGNORE_ACTION_TYPES:
                continue  # ignore these

            else:
                # not processing these
                debug(f"Unknown action: {original_action_type}", action, data)

            test_for_missing_keys = original_item.get(original_message_type, {}).keys()
            missing_keys = test_for_missing_keys - CDY._KNOWN_KEYS

            if not data:
                debug(
                    f"Parse of action returned empty results: {original_action_type}",
                    action,
                )

            if missing_keys:
                debug(
                    f"Missing keys found: {missing_keys}",
                    f"Message type: {original_message_type}",
                    f"Action type: {original_action_type}",
                    f"Action: {action}",
                    f"Parsed data: {data}",
                )

            if original_message_type:

                new_index = remove_prefixes(original_message_type, "liveChat")
                new_index = remove_suffixes(new_index, "Renderer")
                data["message_type"] = camel_case_split(new_index)

                # TODO add option to keep placeholder items
                if original_message_type in CDY._KNOWN_IGNORE_MESSAGE_TYPES:
                    continue
                    # skip placeholder items
                elif (
                    original_message_type
                    not in CDY._KNOWN_ACTION_TYPES[original_action_type]
                ):
                    debug(
                        f'Unknown message type "{original_message_type}" for action "{original_action_type}"',
                        f"New message type: {data['message_type']}",
                        f"Action: {action}",
                        f"Parsed data: {data}",
                    )

            else:  # no type # can ignore message
                debug(
                    "No message type",
                    f"Action type: {original_action_type}",
                    f"Action: {action}",
                    f"Parsed data: {data}",
                )
                continue

            yield data

    except Exception as ex:
        raise Exception(f"translator failed on json line {lineno}: {ex!r}")
