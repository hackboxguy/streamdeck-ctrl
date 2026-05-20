#!/bin/bash
# Launch Kodi to its home screen.
# If Kodi is already running and playing something, stop the playback.
LAUNCHER="/home/pi/micropanel/usr/bin/launcher-client"
SRV="127.0.0.1:8081"
KODI="http://127.0.0.1:8080/jsonrpc"

RUNNING=$("$LAUNCHER" --srv="$SRV" --command=get-running-app 2>/dev/null)

if [ "$RUNNING" = "media-player" ]; then
    # Kodi is running — stop any active playback (video + picture players).
    # Harmless no-op if nothing is playing.
    curl -s "$KODI" -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","method":"Player.Stop","params":{"playerid":1},"id":1}' \
        --connect-timeout 2 > /dev/null 2>&1
    curl -s "$KODI" -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","method":"Player.Stop","params":{"playerid":2},"id":1}' \
        --connect-timeout 2 > /dev/null 2>&1
    exit 0
fi

# Kodi not running — transition through Home first
[ "$RUNNING" != "none" ] && "$LAUNCHER" --srv="$SRV" --command=stop-app && sleep 0.5
"$LAUNCHER" --srv="$SRV" --command=start-app --command-arg=media-player
