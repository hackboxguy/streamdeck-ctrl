#!/bin/bash
# Dual Video key: play dual-player-video-1.mp4 / -2.mp4 from the USB stick,
# one per HDMI output, through the launcher's "dual-video" entry (its
# dual-video.sh finds the pair in the stick's top folder or Videos/ and runs
# dual-video-player; the launcher owns it, so Home and the Player keys work).
#
#   launch-dual-video.sh          start it (the key's press); reports the task
#                                 state: success once the player answers, failure
#                                 (with the reason in the journal) otherwise
#   launch-dual-video.sh state    the key's state_watch: "missing" (no stick or no
#                                 pair: greyed out, presses ignored), "ready"
#                                 (press to play), "playing" (green border)
set -u
DUAL="${DUAL_VIDEO_SH:-/home/pi/micropanel/share/qt-apps/dual-video.sh}"
LAUNCHER="/home/pi/micropanel/usr/bin/launcher-client"
SRV="127.0.0.1:8081"
APP=dual-video
ID=app.dual_video
NOTIFY_SOCK="${NOTIFY_SOCK:-/run/streamdeck-ctrl/notify.sock}"
PLAYER_SOCK=/tmp/dual-video-player.sock

running_app() { "$LAUNCHER" --srv="$SRV" --command=get-running-app 2>/dev/null; }
log() { logger -t dual-video-key -- "$*" 2>/dev/null; echo "dual-video-key: $*" >&2; }
notify() {
    [ -S "$NOTIFY_SOCK" ] || return 0
    echo "{\"id\":\"$ID\",\"state\":\"$1\"}" | socat -t 1 - UNIX-CONNECT:"$NOTIFY_SOCK" >/dev/null 2>&1 || true
}

if [ "${1:-}" = state ]; then
    if [ "$(running_app)" = "$APP" ]; then
        echo playing
    elif [ -x "$DUAL" ] && "$DUAL" --check >/dev/null 2>&1; then
        echo ready
    else
        echo missing
    fi
    exit 0
fi

if [ "$(running_app)" = "$APP" ]; then
    notify success   # already playing: nothing to do
    exit 0
fi
if [ ! -x "$DUAL" ]; then
    log "$DUAL not installed"
    notify failure
    exit 1
fi
if ! why=$("$DUAL" --check 2>&1); then
    log "not starting: ${why:-no clips}"
    notify failure
    exit 1
fi

running=$(running_app)
if [ -n "$running" ] && [ "$running" != none ]; then
    "$LAUNCHER" --srv="$SRV" --command=stop-app >/dev/null
    sleep 0.5
fi
"$LAUNCHER" --srv="$SRV" --command=start-app --command-arg="$APP" >/dev/null

# success once the player's control socket answers (it opens after preroll)
for _ in $(seq 1 20); do
    if [ -S "$PLAYER_SOCK" ] && echo status | socat -t 1 - UNIX-CONNECT:"$PLAYER_SOCK" 2>/dev/null \
            | grep -q '"player":"dual-video-player"'; then
        notify success
        exit 0
    fi
    sleep 0.5
done
log "dual-video-player did not start (see journalctl for qt-demo-launcher)"
notify failure
exit 1
