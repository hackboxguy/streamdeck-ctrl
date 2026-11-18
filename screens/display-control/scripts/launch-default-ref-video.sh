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
for _ in 1 2 3; do
    RUNNING=$("$LAUNCHER" --srv="$SRV" --command=get-running-app 2>/dev/null | head -n 1)
    case "$RUNNING" in ""|*[!a-z0-9_.-]*) sleep 0.2 ;; *) break ;; esac
done
launcher() {   # launcher COMMAND [APP], once more if the answer is lost
    local out
    for _ in 1 2 3; do
        out=$("$LAUNCHER" --srv="$SRV" --command="$1" ${2:+--command-arg="$2"} 2>&1)
        case "$out" in OK*|ERROR:*) return 0 ;; esac
        sleep 0.3
    done
    echo "default-ref-video: launcher $1 $2: ${out:-no answer}" >&2
}

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
    # Kodi not running: end the running app first. The launcher now and then
    # resets a connection while it stops an app, so each command is retried
    if [ "$RUNNING" != "none" ]; then
        launcher stop-app
        for _ in $(seq 1 20); do
            [ "$("$LAUNCHER" --srv="$SRV" --command=get-running-app 2>/dev/null)" = none ] && break
            sleep 0.1
        done
    fi
    launcher start-app media-player
    # Wait (up to 15 s) for Kodi's JSON-RPC, checking every 0.25 s
    for _ in $(seq 1 60); do
        curl -s "$KODI" -H "Content-Type: application/json" \
            -d '{"jsonrpc":"2.0","method":"JSONRPC.Ping","id":1}' \
            --connect-timeout 1 -m 1 2>/dev/null | grep -q pong && break
        sleep 0.25
    done
fi

# Play the chosen reference video. Kodi's JSON-RPC can answer before its
# player is ready (an Open then gets lost, or something Kodi resumes replaces
# it), so open it at once and check: open again until the chosen video plays,
# instead of a fixed wait (it was 3 s, now ~0.5 s on a Pi 4).
playing_it() {
    curl -s "$KODI" -H "Content-Type: application/json" \
        -d '{"jsonrpc":"2.0","method":"Player.GetItem","params":{"playerid":1,"properties":["file"]},"id":1}' \
        --connect-timeout 1 -m 2 2>/dev/null | grep -qF "$VIDEO_NAME"
}
for attempt in 1 2 3 4 5; do
    curl -s "$KODI" -H "Content-Type: application/json" \
        -d "{\"jsonrpc\":\"2.0\",\"method\":\"Player.Open\",\"params\":{\"item\":{\"file\":\"$VIDEO\"}},\"id\":1}" \
        --connect-timeout 2 > /dev/null 2>&1
    for _ in 1 2 3 4 5 6 7 8; do
        playing_it && exit 0
        sleep 0.25
    done
    echo "default-ref-video: not playing yet, opening again ($attempt)" >&2
done
echo "default-ref-video: Kodi did not play $VIDEO" >&2
exit 1
