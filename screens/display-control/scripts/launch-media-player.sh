#!/bin/bash
# Stop any running app, then launch media-player (Kodi)
LAUNCHER="/home/pi/micropanel/usr/bin/launcher-client"
SRV="127.0.0.1:8081"

"$LAUNCHER" --srv="$SRV" --command=stop-app
"$LAUNCHER" --srv="$SRV" --command=start-app --command-arg=media-player
