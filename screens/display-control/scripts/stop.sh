#!/bin/bash
# Stop key: one key for "stop what is on screen", in two stages.
#
#   stop.sh          the press:
#                    1. a video plays (Kodi, Dual Video, USB Media, the SDR/HDR
#                       stand, mpv): stop it (player-ctl.sh stop). Kodi then
#                       shows its own home screen and stays open, to pick the
#                       next video; the other players close.
#                    2. nothing plays, but an app runs (Kodi at its menu, the
#                       cluster demo, ...): back to the launcher's home screen
#                       (launch-home.sh, the Home key).
#                    The Home key always does 2 at once (in Kodi: closes Kodi).
#   stop.sh state    the key's state_watch: "on" while something plays or an
#                    app runs (lit: pressing it does something), "off" at the
#                    launcher's home screen; exits non-zero (the key stays as
#                    it is) when the launcher does not answer
#
# Replaces the former Player Stop and Cluster Stop keys (their labels are
# aliases of this key, so older USB layout files still load).
set -u
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
LAUNCHER="${LAUNCHER_CLIENT:-/home/pi/micropanel/usr/bin/launcher-client}"
SRV="127.0.0.1:8081"
ID=app.stop
NOTIFY_SOCK="${NOTIFY_SOCK:-/run/streamdeck-ctrl/notify.sock}"

# The launcher's running app id, "none", or nothing when it does not answer
# (it now and then resets a connection when queries arrive together): one retry.
launcher_app() {
    local a i
    for i in 1 2; do
        a=$("$LAUNCHER" --srv="$SRV" --command=get-running-app 2>/dev/null | head -n 1)
        case "$a" in
            ""|*[!a-z0-9_.-]*) sleep 0.2 ;;
            *) echo "$a"; return 0 ;;
        esac
    done
    return 1
}
# on / off; fails (the key keeps its state) when the launcher does not answer
state() {
    local app
    [ "$("$DIR/player-ctl.sh" which 2>/dev/null)" != none ] && { echo on; return 0; }
    app=$(launcher_app) || return 1
    if [ "$app" = none ]; then echo off; else echo on; fi
}
notify() {
    [ -S "$NOTIFY_SOCK" ] || return 0
    echo "{\"id\":\"$ID\",\"state\":\"$1\"}" | socat -t 1 - UNIX-CONNECT:"$NOTIFY_SOCK" >/dev/null 2>&1 || true
}

if [ "${1:-}" = state ]; then
    state
    exit
fi

if [ "$("$DIR/player-ctl.sh" which 2>/dev/null)" != none ]; then
    "$DIR/player-ctl.sh" stop; rc=$?
    sleep 0.5
else
    "$DIR/launch-home.sh"; rc=$?
fi
s=$(state) && notify "$s"
exit $rc
