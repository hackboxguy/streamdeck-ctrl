#!/bin/bash
# Launch Kodi and play default video (flower.mkv)
# Skips if flower.mkv is already playing
LAUNCHER="/home/pi/micropanel/usr/bin/launcher-client"
SRV="127.0.0.1:8081"
KODI="http://127.0.0.1:8080/jsonrpc"
VIDEO="/home/pi/micropanel/usr/share/micropanel/media/videos/flower.mkv"

# Check if Kodi is running
RUNNING=$("$LAUNCHER" --srv="$SRV" --command=get-running-app 2>/dev/null)

if [ "$RUNNING" = "media-player" ]; then
    # Kodi is running — check what's currently playing
    ITEM=$(curl -s "$KODI" -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","method":"Player.GetItem","params":{"playerid":1,"properties":["file"]},"id":1}' \
        --connect-timeout 2 2>/dev/null)
    # If flower.mkv is already playing, do nothing
    if echo "$ITEM" | grep -q "flower.mkv"; then
        exit 0
    fi
    # Stop current playback (slideshow, other video, etc.)
    curl -s "$KODI" -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","method":"Player.Stop","params":{"playerid":1},"id":1}' \
        --connect-timeout 2 > /dev/null 2>&1
    # Also stop picture slideshow player if active
    curl -s "$KODI" -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","method":"Player.Stop","params":{"playerid":2},"id":1}' \
        --connect-timeout 2 > /dev/null 2>&1
else
    # Kodi not running — stop current app and start it
    "$LAUNCHER" --srv="$SRV" --command=stop-app
    "$LAUNCHER" --srv="$SRV" --command=start-app --command-arg=media-player
    # Wait for Kodi JSON-RPC to become available
    for i in $(seq 1 15); do
        curl -s "$KODI" -H "Content-Type: application/json" \
            -d '{"jsonrpc":"2.0","method":"JSONRPC.Ping","id":1}' \
            --connect-timeout 1 > /dev/null 2>&1 && break
        sleep 1
    done
fi

# Play default video
curl -s "$KODI" -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"Player.Open\",\"params\":{\"item\":{\"file\":\"$VIDEO\"}},\"id\":1}" \
    --connect-timeout 2 > /dev/null 2>&1
