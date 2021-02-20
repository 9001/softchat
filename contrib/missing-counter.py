#! /usr/bin/python3
# Script that compares two live chat dumps of the same stream to determine
# roughly how many messages are missing from the replay.

import json
import sys

deleted = []
deleted_authors = []
a = []
b = []
deleted_author_timestamps = dict()
last_ts = 0
all_live_ids = set()
all_replay_ids = set()

print("Provide two chat dumps with the live chat dump first")

with open(sys.argv[1], "r", encoding="utf-8") as f:
    a = json.load(f)
    for m in a:
        if "timestamp" in m:
            last_ts = m["timestamp"]
        if m["action_type"] == "mark_chat_item_as_deleted":
            deleted.append(m["target_message_id"])
        if m["action_type"] == "mark_chat_items_by_author_as_deleted":
            deleted_authors.append(m["author"]["id"])
            deleted_author_timestamps[m["author"]["id"]] = last_ts
        if m["action_type"] == "add_chat_item":
            all_live_ids.add(m["message_id"])

with open(sys.argv[2], "r", encoding="utf-8") as f:
    b = json.load(f)
    for m in b:
        if m["action_type"] == "add_chat_item":
            all_replay_ids.add(m["message_id"])

# Ensure both sets of messages begin and end on the same message
for i, m in enumerate(a):
    if m["action_type"] == "add_chat_item":
        if m["message_id"] in all_replay_ids:
            a = a[i:]
            break

for i, m in enumerate(reversed(a)):
    if m["action_type"] == "add_chat_item":
        if m["message_id"] in all_replay_ids:
            a = a[: len(a) - i]
            break

for i, m in enumerate(b):
    if m["action_type"] == "add_chat_item":
        if m["message_id"] in all_live_ids:
            b = b[i:]
            break

for i, m in enumerate(reversed(b)):
    if m["action_type"] == "add_chat_item":
        if m["message_id"] in all_live_ids:
            b = b[: len(b) - i]
            break

# Sorting gets rid of all out of order messages
# a.sort(key=lambda x: x["timestamp"] if 'timestamp' in x else 0)
# b.sort(key=lambda x: x["timestamp"] if 'timestamp' in x else 0)

replay_no_author_messages = 0
keys = set()
for m in b:
    if m["action_type"] != "add_chat_item":
        continue
    if "author" not in m or "id" not in m["author"]:
        replay_no_author_messages += 1
        continue

    keys.add(m["message_id"])

print(f"Live chat replay messages: {len(keys)}")
if replay_no_author_messages:
    print(f"Live replay messages without author: {replay_no_author_messages}")

known_deletions = 0
# Messages that were deleted but are present in the chat replay
known_undeletions = 0
known_author_undeletions = 0
replacements = 0
dump_messages_with_author = 0
dump_messages_with_author_incl_deleted = 0
missing_scs = 0
indices = dict()
missing_red_scs = []
diff = []
for i, m in enumerate(a):
    if m["action_type"] == "replace_chat_item":
        replacements += 1
        if m["message_id"] in keys:
            keys.remove(m["message_id"])

    if m["action_type"] != "add_chat_item" or "author" not in m:
        continue
    dump_messages_with_author_incl_deleted += 1
    if m["message_id"] in deleted:
        known_deletions += 1
        if m["message_id"] in keys:
            # Haven't actually seen an instances of this one
            print(f"Undeleted by ID {m['message_id']}")
            known_undeletions += 1
        else:
            continue
    if m["author"]["id"] in deleted_author_timestamps:
        # if m["timestamp"] <= deleted_author_timestamps[m["author"]["id"]]:
        known_deletions += 1
        if m["message_id"] in keys:
            # print(f"Undeleted by author {m['message']}")
            known_author_undeletions += 1
        else:
            continue
        # else:
        #    pass

    dump_messages_with_author += 1
    indices[m["message_id"]] = i
    if m["message_id"] not in keys:
        if m["message_type"] == "paid_message":
            missing_scs += 1
            if m["header_background_colour"] == "#d00000ff":
                missing_red_scs.append(m["message_id"])
        diff.append(m)
    else:
        keys.remove(m["message_id"])

print(f"Messages in live dump: {dump_messages_with_author_incl_deleted}")
print(f"Less known net deletions: {dump_messages_with_author}")
print(f"Known deletions: {known_deletions}")
print(
    f"Known undeletions (mark_chat_items_by_author_as_deleted but present in replay): {known_author_undeletions}"
)
# A message can be replaced more than once so this isn't necessarily correct
print(
    f"Messages present in live dump but not replay: "
    f"{len(diff) - replacements} ({(len(diff) - replacements) / (dump_messages_with_author - replacements) * 100}%)"
)

if len(keys) > 0:
    print(f"Messages present in replay but not live dump (not delivered?): {len(keys)}")

    extra_scs = 0
    extra_red_scs = []

    for m in b:
        if "message_id" not in m or m["message_id"] not in keys:
            continue
        if m["message_type"] == "paid_message":
            extra_scs += 1
            if m["header_background_colour"] == "#d00000ff":
                extra_red_scs.append(m["message_id"])

    if extra_scs > 0:
        print(f"Superchats present in replay but not live dump: {extra_scs}")
        if len(extra_red_scs) > 0:
            print(f"Missing red superchats: {len(extra_red_scs)}")
            for m in extra_red_scs:
                print(m)

out_of_order = 0
idx = 0
for m in b:
    if "message_id" not in m or m["message_id"] not in indices:
        continue
    i = indices[m["message_id"]]
    if i < idx:
        out_of_order += 1
    idx = i

print(f"Messages in different order in replay: {out_of_order}")

print(f"Superchats present in live dump but not replay: {missing_scs}")
if len(missing_red_scs) > 0:
    print(f"Missing red superchats: {len(missing_red_scs)}")
    for m in missing_red_scs:
        print(m)
