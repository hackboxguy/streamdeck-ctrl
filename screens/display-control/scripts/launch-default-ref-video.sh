#!/bin/bash
# Launch Kodi and play the default reference video.
# Prefers ref-video.mp4 if present, otherwise falls back to flower.mkv.
# Skips if the chosen video is already playing.
LAUNCHER="/home/pi/micropanel/usr/bin/launcher-client"
SRV="127.0.0.1:8081"
KODI="http://127.0.0.1:8080/jsonrpc"
VIDEO_DIR="/home/pi/micropanel/usr/share/micropanel/media/videos"
REF_VIDEO="/home/pi/micropanel/share/sp6bins/config/ref-video.mp4"
FLOWER="$VIDEO_DIR/flower.mkv"

# Choose which video to play
if [ -f "$REF_VIDEO" ]; then
    VIDEO="$REF_VIDEO"
else
    VIDEO="$FLOWER"
fi
VIDEO_NAME=$(basename "$VIDEO")

# Check if Kodi is running
RUNNING=$("$LAUNCHER" --srv="$SRV" --command=get-running-app 2>/dev/null)

if [ "$RUNNING" = "media-player" ]; then
    # Kodi is running — check what's currently playing
    ITEM=$(curl -s "$KODI" -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","method":"Player.GetItem","params":{"playerid":1,"properties":["file"]},"id":1}' \
        --connect-timeout 2 2>/dev/null)
    # If the chosen video is already playing, do nothing
    if echo "$ITEM" | grep -q "$VIDEO_NAME"; then
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
    # Kodi not running — transition through Home first
    [ "$RUNNING" != "none" ] && "$LAUNCHER" --srv="$SRV" --command=stop-app && sleep 0.5
    "$LAUNCHER" --srv="$SRV" --command=start-app --command-arg=media-player
    # Wait for Kodi JSON-RPC to become available
    for i in $(seq 1 15); do
        curl -s "$KODI" -H "Content-Type: application/json" \
            -d '{"jsonrpc":"2.0","method":"JSONRPC.Ping","id":1}' \
            --connect-timeout 1 > /dev/null 2>&1 && break
        sleep 1
    done
fi

# Play the chosen reference video
curl -s "$KODI" -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"Player.Open\",\"params\":{\"item\":{\"file\":\"$VIDEO\"}},\"id\":1}" \
    --connect-timeout 2 > /dev/null 2>&1
