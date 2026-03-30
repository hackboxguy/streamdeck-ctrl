#!/bin/bash
# Launch Kodi slideshow — starts Kodi if not running, then opens slideshow
# Skips if slideshow is already playing
LAUNCHER="/home/pi/micropanel/usr/bin/launcher-client"
SRV="127.0.0.1:8081"
KODI="http://127.0.0.1:8080/jsonrpc"
PICTURES="/home/pi/micropanel/share/qt-apps/Pictures/"

# Check if Kodi is running
RUNNING=$("$LAUNCHER" --srv="$SRV" --command=get-running-app 2>/dev/null)

if [ "$RUNNING" = "media-player" ]; then
    # Kodi is running — check if slideshow is already playing
    RESP=$(curl -s "$KODI" -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","method":"Player.GetActivePlayers","params":{},"id":1}' \
        --connect-timeout 2 2>/dev/null)
    # If picture player (type=picture) is active, slideshow is running
    if echo "$RESP" | grep -q '"type":"picture"'; then
        exit 0
    fi
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

# Start slideshow
curl -s "$KODI" -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"Player.Open\",\"params\":{\"item\":{\"directory\":\"$PICTURES\"},\"options\":{\"shuffled\":false,\"repeat\":\"all\"}},\"id\":1}" \
    --connect-timeout 2 > /dev/null 2>&1
