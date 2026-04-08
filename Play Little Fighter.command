#!/bin/bash
cd "$(dirname "$0")"
"/Applications/DOSBox Staging.app/Contents/MacOS/dosbox" -conf dosbox.conf
sleep 2
osascript -e 'tell application "Terminal" to close front window' &>/dev/null &
