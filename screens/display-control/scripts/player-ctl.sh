#!/bin/bash
# player-ctl.sh - the Stream Deck's Player keys: drive whatever is playing.
#
#   player-ctl.sh pause | resume | toggle   freeze / go on / either
#   player-ctl.sh seek -10 | seek +10       jump back / forward (seconds)
#   player-ctl.sh stop                      stop playback
#   player-ctl.sh loop on | off | toggle    repeat the video on screen (Kodi: repeat
#                                           one; dual-video-player: the item, or
#                                           both files in two-file mode)
#   player-ctl.sh loop-status               "on <player>", "off <player>",
#                                           "unknown <player>" or "none" (the
#                                           Player Loop key's state_watch)
#   player-ctl.sh status                    "playing <player>", "paused <player>",
#                                           "unknown <player>" or "none" (the
#                                           Player Pause key's state_watch)
#   player-ctl.sh volume up | down | N      volume +/-5 or to N (0-100)
#   player-ctl.sh mute on | off | toggle
#   player-ctl.sh volume-level              "45%", "muted" or "--" (the Volume key)
#   player-ctl.sh mute-status               "on <player>", "off <player>" or "none"
#                                           (the Mute key's state_watch)
#   player-ctl.sh stop-all                  stop every player that is active (Home key)
#   player-ctl.sh which                     the player the keys would drive
#
# Each player is an executable in players.d/, asked in name order; the first
# whose "active" succeeds is driven. A player file answers:
#   active                 exit 0 if it is playing (or paused) now
#   status                 playing | paused | unknown
#   pause | resume | toggle | stop | seek <[+-]seconds>
#   loop <on|off|toggle>   loop-status: on | off | unknown
#   has-audio              exit 0 if it has a volume now (volume and mute go
#                          to the first such player; Kodi also at its menu)
#   volume <up|down|N>     volume-level: 0-100
#   mute <on|off|toggle>   mute-status: on | off | unknown
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
LOOP_KEY=player.loop
MUTE_KEY=audio.mute
VOLUME_KEY=audio.volume

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

# Set a key's state (or a live key's value) right away, not at its next poll:
# notify KEY on|off [state|value]
notify() {
    [ -S "$NOTIFY_SOCK" ] || return 0
    python3 - "$NOTIFY_SOCK" "$1" "$2" "${3:-state}" <<'PY' >/dev/null 2>&1 || true
import json, socket, sys
s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.settimeout(1)
s.connect(sys.argv[1])
s.sendall((json.dumps({"id": sys.argv[2], sys.argv[4]: sys.argv[3]}) + "\n").encode())
s.recv(256)
PY
}
# Light the Player Pause key (on = paused)
notify_pause() { if [ "$1" = paused ]; then notify "$PAUSE_KEY" on; else notify "$PAUSE_KEY" off; fi; }
# Light the Player Loop key (on = looping; unknown: leave it as it is)
notify_loop() {
    case "$1" in on) notify "$LOOP_KEY" on ;; unknown) ;; *) notify "$LOOP_KEY" off ;; esac
}

name() { basename "$1" .sh | sed 's/^[0-9]*-//'; }

# the first player with a volume now
audio_player() {
    local p
    for p in "$PLAYERS"/*.sh; do
        [ -x "$p" ] || continue
        if "$p" has-audio >/dev/null 2>&1; then
            echo "$p"
            return 0
        fi
    done
    return 1
}
# what the Volume key shows: "45%", "muted", or "--" with nothing to set
level() {
    local p v
    p=$(audio_player) || { echo "--"; return; }
    if [ "$("$p" mute-status 2>/dev/null)" = on ]; then echo muted; return; fi
    v=$("$p" volume-level 2>/dev/null)
    case "$v" in [0-9]*) echo "$v%" ;; *) echo "--" ;; esac
}
# after a volume or mute change: both keys at once
notify_audio() {
    local p=$1 m
    m=$("$p" mute-status 2>/dev/null)
    case "$m" in on|off) notify "$MUTE_KEY" "$m" ;; esac
    notify "$VOLUME_KEY" "$(level)" value
}

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
    loop)
        case "${2:-}" in on|off|toggle) ;; *) echo "usage: $0 loop on|off|toggle" >&2; exit 2 ;; esac
        p=$(active_player) || { echo "nothing is playing" >&2; notify_loop none; exit 1; }
        "$p" loop "$2"; rc=$?
        sleep 0.2
        notify_loop "$("$p" loop-status 2>/dev/null)"
        echo "$(name "$p"): loop $2"
        exit $rc
        ;;
    volume)
        case "${2:-}" in up|down|[0-9]*) ;; *) echo "usage: $0 volume up|down|0-100" >&2; exit 2 ;; esac
        p=$(audio_player) || { echo "nothing with sound is running" >&2; exit 1; }
        "$p" volume "$2"; rc=$?
        notify_audio "$p"
        echo "$(name "$p"): volume $("$p" volume-level 2>/dev/null)"
        exit $rc
        ;;
    mute)
        case "${2:-}" in on|off|toggle) ;; *) echo "usage: $0 mute on|off|toggle" >&2; exit 2 ;; esac
        p=$(audio_player) || { echo "nothing with sound is running" >&2; notify "$MUTE_KEY" off; exit 1; }
        "$p" mute "$2"; rc=$?
        notify_audio "$p"
        echo "$(name "$p"): mute $("$p" mute-status 2>/dev/null)"
        exit $rc
        ;;
    mute-status)
        if p=$(audio_player); then
            echo "$("$p" mute-status 2>/dev/null || echo unknown) $(name "$p")"
        else
            echo none
        fi
        ;;
    volume-level)
        level
        ;;
    loop-status)
        if p=$(active_player); then
            echo "$("$p" loop-status 2>/dev/null || echo unknown) $(name "$p")"
        else
            echo none
        fi
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
        notify_loop none
        ;;
    which)
        p=$(active_player) && name "$p" || echo none
        ;;
    *)
        echo "usage: $0 pause|resume|toggle|stop|seek [+-]S|loop on|off|toggle|volume up|down|N|mute on|off|toggle|status|loop-status|mute-status|volume-level|stop-all|which" >&2
        exit 2
        ;;
esac
