#!/bin/bash
# Return to qt-demo-launcher home screen by stopping any running app
# Skip if already at home (no app running)
LAUNCHER="/home/pi/micropanel/usr/bin/launcher-client"
SRV="127.0.0.1:8081"

RUNNING=$("$LAUNCHER" --srv="$SRV" --command=get-running-app 2>/dev/null)
[ "$RUNNING" = "none" ] && exit 0

"$LAUNCHER" --srv="$SRV" --command=stop-app
