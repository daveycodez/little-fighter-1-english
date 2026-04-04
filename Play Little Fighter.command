#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
open -a "/opt/homebrew/Caskroom/dosbox/0.74-3,3/dosbox.app" --args -c "mount c \"$SCRIPT_DIR\"" -c "c:" -c "PLAY.COM"
sleep 2
osascript -e 'tell application "Terminal" to close front window' &>/dev/null &
