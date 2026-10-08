#!/bin/bash
# Launch Kodi and play the default reference video - the same rule as the
# launcher's Demo Video tile (kodi-video.sh):
#   1. a video on a USB stick: the first in its Videos/ folder, else the
#      first at its top level (e.g. sample-video.mp4 copied straight on it)
#   2. ref-video.mp4 (the image's reference video)
#   3. flower.mkv
# The USB rule is the launcher's own helper (kodi-usb-common.sh); without it
# (an older image) the key skips step 1. Skips if the chosen video is
# already playing.
LAUNCHER="/home/pi/micropanel/usr/bin/launcher-client"
SRV="127.0.0.1:8081"
KODI="http://127.0.0.1:8080/jsonrpc"
VIDEO_DIR="/home/pi/micropanel/usr/share/micropanel/media/videos"
REF_VIDEO="/home/pi/micropanel/share/sp6bins/config/ref-video.mp4"
FLOWER="$VIDEO_DIR/flower.mkv"
USB_COMMON="${KODI_USB_COMMON:-/home/pi/micropanel/share/qt-apps/kodi-usb-common.sh}"

# Choose which video to play
if [ -f "$REF_VIDEO" ]; then
    VIDEO="$REF_VIDEO"
else
    VIDEO="$FLOWER"
fi
if [ -r "$USB_COMMON" ]; then
    # shellcheck source=/dev/null
    . "$USB_COMMON"
    if command -v find_usb_video >/dev/null 2>&1 && usb_video=$(find_usb_video); then
        VIDEO="$usb_video"
    fi
fi
echo "default-ref-video: $VIDEO"
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
    # Give Kodi extra time to finish initializing after JSON-RPC ping
    # responds — its HTTP server can answer before the player is ready
    # and any autoresume of the last-played item has settled.
    sleep 3
    # Cancel any autoresume that Kodi may have started during boot
    curl -s "$KODI" -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","method":"Player.Stop","params":{"playerid":1},"id":1}' \
        --connect-timeout 2 > /dev/null 2>&1
    curl -s "$KODI" -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","method":"Player.Stop","params":{"playerid":2},"id":1}' \
        --connect-timeout 2 > /dev/null 2>&1
fi

# Play the chosen reference video
curl -s "$KODI" -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"Player.Open\",\"params\":{\"item\":{\"file\":\"$VIDEO\"}},\"id\":1}" \
    --connect-timeout 2 > /dev/null 2>&1
