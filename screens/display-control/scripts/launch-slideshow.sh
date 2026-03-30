#!/bin/bash
# Stop any running app, then launch slideshow
# Skip if slideshow is already running
LAUNCHER="/home/pi/micropanel/usr/bin/launcher-client"
SRV="127.0.0.1:8081"

RUNNING=$("$LAUNCHER" --srv="$SRV" --command=get-running-app 2>/dev/null)
[ "$RUNNING" = "slideshow" ] && exit 0

"$LAUNCHER" --srv="$SRV" --command=stop-app
"$LAUNCHER" --srv="$SRV" --command=start-app --command-arg=slideshow
