#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
"/Applications/RetroArch.app/Contents/MacOS/RetroArch" \
  -L "$HOME/Library/Application Support/RetroArch/cores/dosbox_pure_libretro.dylib" \
  "$SCRIPT_DIR/PLAY.COM"
sleep 2
osascript -e 'tell application "Terminal" to close front window' &>/dev/null &
