#!/bin/bash
# player-ctl.sh - the Stream Deck's Player keys: drive whatever is playing.
#
#   player-ctl.sh pause | resume | toggle   freeze / go on / either
#   player-ctl.sh seek -10 | seek +10       jump back / forward (seconds)
#   player-ctl.sh stop                      stop playback
#   player-ctl.sh status                    "playing <player>", "paused <player>",
#                                           "unknown <player>" or "none" (the
#                                           Player Pause key's state_watch)
#   player-ctl.sh stop-all                  stop every player that is active (Home key)
#   player-ctl.sh which                     the player the keys would drive
#
# Each player is an executable in players.d/, asked in name order; the first
# whose "active" succeeds is driven. A player file answers:
#   active                 exit 0 if it is playing (or paused) now
#   status                 playing | paused | unknown
#   pause | resume | toggle | stop | seek <[+-]seconds>
# Adding a player = adding a file there (an mpv-based player that opens its
# IPC socket at /tmp/mpv-socket or /tmp/mpv-*.sock needs none: mpv.sh finds it).
#
# The shoot-out sync comes first: it keeps Kodi and the Zidoo on one frame, so
# Kodi must not be driven directly while it runs.
set -u
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PLAYERS="${PLAYER_CTL_DIR:-$DIR/players.d}"
NOTIFY_SOCK="${NOTIFY_SOCK:-/run/streamdeck-ctrl/notify.sock}"
PAUSE_KEY=player.pause

active_player() {
    local p
    for p in "$PLAYERS"/*.sh; do
        [ -x "$p" ] || continue
        if "$p" active >/dev/null 2>&1; then
            echo "$p"
            return 0
        fi
    done
    return 1
}

# Light the Player Pause key (on = paused) right away, not at the next poll
notify_pause() {
    local state=off
    [ "$1" = paused ] && state=on
    [ -S "$NOTIFY_SOCK" ] || return 0
    python3 - "$NOTIFY_SOCK" "$PAUSE_KEY" "$state" <<'PY' >/dev/null 2>&1 || true
import json, socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(1)
s.connect(sys.argv[1])
s.sendall((json.dumps({"id": sys.argv[2], "state": sys.argv[3]}) + "\n").encode())
s.recv(256)
PY
}

name() { basename "$1" .sh | sed 's/^[0-9]*-//'; }

cmd=${1:-}
case "$cmd" in
    pause|resume|toggle|stop)
        p=$(active_player) || { echo "nothing is playing" >&2; notify_pause none; exit 1; }
        "$p" "$cmd"; rc=$?
        if [ "$cmd" = stop ]; then
            notify_pause none
        else
            sleep 0.3
            notify_pause "$("$p" status 2>/dev/null)"
        fi
        echo "$(name "$p"): $cmd"
        exit $rc
        ;;
    seek)
        case "${2:-}" in
            [+-][0-9]*|[0-9]*) ;;
            *) echo "usage: $0 seek [+-]SECONDS" >&2; exit 2 ;;
        esac
        p=$(active_player) || { echo "nothing is playing" >&2; exit 1; }
        "$p" seek "$2"; rc=$?
        echo "$(name "$p"): seek $2"
        exit $rc
        ;;
    status)
        if p=$(active_player); then
            echo "$("$p" status 2>/dev/null || echo unknown) $(name "$p")"
        else
            echo none
        fi
        ;;
    stop-all)
        for p in "$PLAYERS"/*.sh; do
            [ -x "$p" ] || continue
            if "$p" active >/dev/null 2>&1; then
                "$p" stop >/dev/null 2>&1
                echo "stopped $(name "$p")"
            fi
        done
        notify_pause none
        ;;
    which)
        p=$(active_player) && name "$p" || echo none
        ;;
    *)
        echo "usage: $0 pause|resume|toggle|stop|seek [+-]S|status|stop-all|which" >&2
        exit 2
        ;;
esac
