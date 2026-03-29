#!/bin/bash
# Stop any running app, then launch disp-settings
# Skip if disp-settings is already running
LAUNCHER="/home/pi/micropanel/usr/bin/launcher-client"
SRV="127.0.0.1:8081"

RUNNING=$("$LAUNCHER" --srv="$SRV" --command=get-running-app 2>/dev/null)
[ "$RUNNING" = "disp-settings" ] && exit 0

"$LAUNCHER" --srv="$SRV" --command=stop-app
"$LAUNCHER" --srv="$SRV" --command=start-app --command-arg=disp-settings
