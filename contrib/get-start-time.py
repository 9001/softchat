#! /usr/bin/env python
# Call with the video URL or ID.
# Useful for videos missing chat replays or unarchived streams, but it needs to
# be used while the stream is live.
# Doesn't really help if the stream had chunks removed due to editing.

import urllib
import re
import sys
import requests
import json
import datetime

try:
    vid = re.search(r"(v=|be/|^)([a-zA-Z0-9_-]{11})", sys.argv[1]).group(2)
except:
    print("Could not identify video ID")
    sys.exit(1)


resp = requests.get(
    f"https://www.youtube.com/get_video_info?video_id={vid}"
).content.decode("utf-8")

jsn = json.loads(urllib.parse.parse_qs(resp)["player_response"][0])

startTime = jsn["microformat"]["playerMicroformatRenderer"]["liveBroadcastDetails"][
    "startTimestamp"
]

print(int(datetime.datetime.fromisoformat(startTime).timestamp()))
