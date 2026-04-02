#!/bin/bash
# Stop any running app (via Home), then launch cluster-demo
# Skip if cluster-demo is already running
LAUNCHER="/home/pi/micropanel/usr/bin/launcher-client"
SRV="127.0.0.1:8081"

RUNNING=$("$LAUNCHER" --srv="$SRV" --command=get-running-app 2>/dev/null)
[ "$RUNNING" = "cluster-demo" ] && exit 0

# Transition through Home first to let qt-demo-launcher reclaim
# the display — direct app-to-app transitions can leave the
# framebuffer in an undefined state (e.g. black screen from Kodi)
[ "$RUNNING" != "none" ] && "$LAUNCHER" --srv="$SRV" --command=stop-app && sleep 0.5

"$LAUNCHER" --srv="$SRV" --command=start-app --command-arg=cluster-demo
