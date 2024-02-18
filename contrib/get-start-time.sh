#! /bin/sh
# Call with the video URL or ID.
# Useful for videos missing chat replays or unarchived streams, but it needs to
# be used while the stream is live.
# Isn't perfect if chunks were removed or the stream went offline temporarily.


id=$(echo "$1" | grep -oE "(v=|be/|^)([a-zA-Z0-9_-]{11})" | sed -E 's/.*(\/|=)//')
ts=$(curl "https://www.youtube.com/watch?v=$id" | grep -oE '"startTimestamp":"[^"]+"' | sed -E 's/.*"([^"]+)"/\1/')
echo "$ts"

