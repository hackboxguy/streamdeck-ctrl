#!/bin/bash
# dual-video-player (br-wrapper micropanel-media-player: USB Media playlists,
# the Dual Video button): its control socket. It plays no sound (video only),
# so it has no volume or mute.
SOCK="${DVP_SOCK:-/tmp/dual-video-player.sock}"
send() { [ -S "$SOCK" ] && printf '%s\n' "$*" | socat -t 3 - UNIX-CONNECT:"$SOCK" 2>/dev/null; }
case "${1:-}" in
    active)  send status | grep -q '"player":"dual-video-player"' ;;
    has-audio) exit 1 ;;
    status)  case "$(send status)" in *'"state":"paused"'*) echo paused ;; *'"state":'*) echo playing ;; *) exit 1 ;; esac ;;
    pause|resume|toggle|stop) send "$1" | grep -q '^ok' ;;
    seek)    send "seek $2" | grep -q '^ok' ;;
    loop)    send "loop $2" | grep -q '^ok' ;;
    loop-status) case "$(send status)" in *'"loop":true'*) echo on ;; *'"loop":false'*) echo off ;; *) echo unknown ;; esac ;;
    *)       exit 2 ;;
esac
