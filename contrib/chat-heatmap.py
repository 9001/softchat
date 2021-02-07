#!/usr/bin/env python3

import sys

# takes an ass file and shows how many messages there are within a 30sec window at each time
# for example to see where a youtube/twitch chatlog is hype
# (see https://github.com/9001/softchat/ for that)

stack = []
basets = 0
maxnum = 0
maxts = 0
with open(sys.argv[1], "rb") as f:
    for ln in [x.decode("utf-8", "ignore") for x in f]:
        if not ln.startswith("Dialogue: 0,"):
            continue

        ts = ln.split(",")[1].split(":")
        ts = 60 * (60 * int(ts[0]) + int(ts[1])) + float(ts[2])
        rm = 0
        for v in stack:
            if v < ts - 10:
                rm += 1

        stack = stack[rm:] + [ts]
        if maxnum < len(stack):
            maxnum = len(stack)
            maxts = ts

        if ts > basets + 30:
            print("{} {}".format(maxnum, maxts))
            basets = ts
            maxnum = 0
            maxts = 0
