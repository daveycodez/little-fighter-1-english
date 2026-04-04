#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"/Applications/DOSBox Staging.app/Contents/MacOS/dosbox" -c "mount c \"$SCRIPT_DIR\"" -c "c:" -c "PLAY.COM"
sleep 2
osascript -e 'tell application "Terminal" to close front window' &>/dev/null &
