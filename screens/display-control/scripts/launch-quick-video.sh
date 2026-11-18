#!/bin/bash
# Quick Video key: a video from the USB stick straight into dual-video-player,
# without Kodi (playing in about half a second; Default Ref Video's Kodi takes
# 7-8 s), through the launcher's hidden "quick-video" entry (its
# quick-video.sh picks the video; the launcher owns the player, so Home, Stop
# and the Player keys work). Video only: the player has no sound.
#
#   launch-quick-video.sh         the press: start the first playable video on
#                                 the stick; while Quick Video plays, the next
#                                 one (wraps around). Reports the task state:
#                                 success once the player plays it, failure
#                                 (reason in journalctl -t quick-video-key)
#   launch-quick-video.sh state   the key's state_watch: "missing" (no stick or
#                                 no video on it: greyed out), "ready", "playing"
#                                 (green border); nothing (the key stays as it
#                                 is) when the launcher does not answer
set -u
QV="${QUICK_VIDEO_SH:-/home/pi/micropanel/share/qt-apps/quick-video.sh}"
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
. "$DIR/launcher-lib.sh"
APP=quick-video
ID=app.quick_video
STATE_DIR="${QUICK_VIDEO_STATE_DIR:-/tmp}"
NOTIFY_SOCK="${NOTIFY_SOCK:-/run/streamdeck-ctrl/notify.sock}"
PLAYER_SOCK="${PLAYER_SOCK:-/tmp/dual-video-player.sock}"

log() { logger -t quick-video-key -- "$*" 2>/dev/null; echo "quick-video-key: $*" >&2; }
notify() {
    [ -S "$NOTIFY_SOCK" ] || return 0
    echo "{\"id\":\"$ID\",\"state\":\"$1\"}" | socat -t 1 - UNIX-CONNECT:"$NOTIFY_SOCK" >/dev/null 2>&1 || true
}

if [ "${1:-}" = state ]; then
    app=$(launcher_app) || exit 1
    if [ "$app" = "$APP" ]; then
        echo playing
    elif [ -x "$QV" ] && "$QV" --check >/dev/null 2>&1; then
        echo ready
    else
        echo missing
    fi
    exit 0
fi

if [ ! -x "$QV" ]; then
    log "$QV not installed (an image without Quick Video)"
    notify failure
    exit 1
fi
if ! why=$("$QV" --check 2>&1); then
    log "not starting: ${why:-no video}"
    notify failure
    exit 1
fi

running=$(launcher_app) || running=""
if [ "$running" = "$APP" ]; then
    # playing: the next video on the stick
    n=$(cut -f1 "$STATE_DIR/quick-video.current" 2>/dev/null)
    case "$n" in ''|*[!0-9]*) n=0 ;; esac
    echo $((n + 1)) > "$STATE_DIR/quick-video.next"
else
    rm -f "$STATE_DIR/quick-video.next"
fi
if [ "$running" != none ] && ! launcher_stop_app; then
    log "${running:-the running app} did not stop"; notify failure; exit 1
fi
rm -f "$STATE_DIR/quick-video.current"
out=$(launcher_cmd start-app "$APP")
case "$out" in
    OK*) ;;
    *) log "the launcher did not start $APP: ${out:-no answer}"; notify failure; exit 1 ;;
esac

# success once the player plays the chosen video
for i in $(seq 1 40); do
    if [ ! -s "$STATE_DIR/quick-video.current" ] && [ "$i" -ge 4 ] && [ "$(launcher_app)" = none ]; then
        break   # quick-video.sh found nothing playable and is gone
    fi
    if [ -s "$STATE_DIR/quick-video.current" ] && [ -S "$PLAYER_SOCK" ]; then
        st=$(echo status | socat -t 1 - UNIX-CONNECT:"$PLAYER_SOCK" 2>/dev/null)
        case "$st" in
            *'"state":"playing"'*)
                IFS=$'\t' read -r n file count < "$STATE_DIR/quick-video.current"
                echo "quick-video: $((n + 1))/$count $(basename "$file")"
                notify success
                exit 0 ;;
        esac
    fi
    sleep 0.25
done
log "no video started (none playable on the stick? see journalctl -u qt-demo-launcher)"
notify failure
exit 1
