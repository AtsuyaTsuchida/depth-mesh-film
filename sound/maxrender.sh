#!/bin/bash
# Open one Max 8 render patch on its own, wait for "end" on udp 7400, then make sure Max has quit.
#   maxrender.sh <patch.maxpat> <timeout seconds> <log>
# Max 8 reopens every patch that was open at its last quit (Crash Recovery/maxworkspace-*.txt).
# Other projects' render patches came back that way and overwrote their WAVs, so the list is
# moved to $TMPDIR/max-workspace-backup (not deleted) before every launch.
set -u
patch=$1; limit=$2; log=$3
ws="$HOME/Library/Application Support/Cycling '74/Max 8/Crash Recovery"
keep="${TMPDIR:-/tmp}/max-workspace-backup"
mkdir -p "$keep"
if pgrep -f "Max.app/Contents/MacOS/Max" >/dev/null; then echo "Max 8 is already running; not starting" >&2; exit 1; fi
for f in "$ws"/maxworkspace-*.txt; do [ -e "$f" ] && mv "$f" "$keep/$(date +%s)-$(basename "$f")"; done
python3 -I "$(dirname "$0")/listen.py" "$limit" > "$log" 2>&1 &
lp=$!
sleep 1
open -a /Applications/Max.app "$patch"
wait $lp
for i in $(seq 1 30); do pgrep -f "Max.app/Contents/MacOS/Max" >/dev/null || break; sleep 1; done
grep -q " end \[\]" "$log" && echo "done $(basename "$patch")" || echo "NO END for $(basename "$patch") (see $log)"
