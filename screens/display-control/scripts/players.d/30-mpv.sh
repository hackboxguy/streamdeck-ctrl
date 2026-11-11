#!/bin/bash
# mpv-based players (qt-mpv-wrapper: --input-ipc-server=/tmp/mpv-socket; any
# other mpv started with an IPC socket at /tmp/mpv-*.sock): mpv's JSON IPC.
SOCKETS="${MPV_SOCKETS:-/tmp/mpv-socket /tmp/mpv-*.sock}"
ipc() {   # ipc SOCKET JSON-COMMAND-ARRAY -> mpv's reply line
    printf '{"command":%s}\n' "$2" | socat -t 2 - UNIX-CONNECT:"$1" 2>/dev/null | head -1
}
# the first socket whose mpv has a file open (idle mpv: "path" unavailable)
find_sock() {
    local s
    for s in $SOCKETS; do
        [ -S "$s" ] || continue
        ipc "$s" '["get_property","path"]' | grep -q '"error":"success"' && { echo "$s"; return 0; }
    done
    return 1
}
S=$(find_sock) || exit 1
case "${1:-}" in
    active)  exit 0 ;;
    status)  case "$(ipc "$S" '["get_property","pause"]')" in *'"data":true'*) echo paused ;; *) echo playing ;; esac ;;
    pause)   ipc "$S" '["set_property","pause",true]' | grep -q success ;;
    resume)  ipc "$S" '["set_property","pause",false]' | grep -q success ;;
    toggle)  ipc "$S" '["cycle","pause"]' | grep -q success ;;
    seek)    ipc "$S" "[\"seek\",${2#+},\"relative\"]" | grep -q success ;;
    stop)    ipc "$S" '["stop"]' | grep -q success ;;
    loop-status) case "$(ipc "$S" '["get_property","loop-file"]')" in
                 *'"data":false'*|*'"data":"no"'*) echo off ;; *'"error":"success"'*) echo on ;; *) echo unknown ;; esac ;;
    loop)    case "$2" in
                 on)  ipc "$S" '["set_property","loop-file","inf"]' | grep -q success ;;
                 off) ipc "$S" '["set_property","loop-file","no"]' | grep -q success ;;
                 *)   if [ "$("$0" loop-status)" = on ]; then "$0" loop off; else "$0" loop on; fi ;;
             esac ;;
    *)       exit 2 ;;
esac
