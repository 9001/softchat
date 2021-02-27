#! /bin/sh
# Re-run softchat with the same parameters.
# Assumes you're running it from the same working directory.
# Run at your own risk on untrusted files.

set -e

if echo "$1" | grep -E -v "\.ass$"; then
  echo "Not an ass file"
  exit 1
fi

cmd=$(head -n 3 "$1" | tail -n 1)

if echo "$cmd" | grep -E -v "^;.*\.json"; then
  echo "Doesn't appear to be a recent softchat subtitle file."
  exit 1
fi

args=$(echo $cmd | cut -c 2-)
eval "python -m softchat $args"
