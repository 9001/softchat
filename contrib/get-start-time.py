#! /bin/sh
# Call with the video URL or ID.
# Useful for videos missing chat replays or unarchived streams, but it needs to
# be used while the stream is live.
# Doesn't really help if the stream had chunks removed due to editing.


id=$(echo "$1" | grep -oE "(v=|be/|^)([a-zA-Z0-9_-]{11})" | sed -E 's/.*(\/|=)//')
ts=$(curl "https://www.youtube.com/watch?v=$id" | grep -oE '"startTimestamp":"[^"]+"' | sed -E 's/.*"([^"]+)"/\1/')
python -c "import datetime; import sys; print(int(datetime.datetime.fromisoformat(sys.argv[1]).timestamp()))" "$ts"

