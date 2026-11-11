#!/bin/bash
# Kodi (the launcher's Media Player): JSON-RPC on :8080. Stop ends playback;
# Kodi itself stays open (Home closes it). Volume and mute are Kodi's own
# (application level): they work whenever Kodi runs, playing or not.
KODI="${KODI_URL:-http://127.0.0.1:8080/jsonrpc}"
STEP=5
rpc() {   # rpc METHOD PARAMS-JSON -> the reply
    curl -s --connect-timeout 1 -m 3 -H 'Content-Type: application/json' \
        -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":$2}" "$KODI"
}
ok() { grep -q '"result"'; }
# the active player's id (video before audio before pictures), "" if none
player_id() {
    rpc Player.GetActivePlayers '{}' | python3 -c '
import json, sys
try:
    players = json.load(sys.stdin).get("result") or []
except ValueError:
    players = []
order = {"video": 0, "audio": 1, "picture": 2}
players.sort(key=lambda p: order.get(p.get("type"), 3))
print(players[0]["playerid"] if players else "")' 2>/dev/null
}
app_prop() {   # app_prop volume|muted
    rpc Application.GetProperties '{"properties":["volume","muted"]}' |
        python3 -c "import json,sys; print(str(json.load(sys.stdin)['result']['$1']).lower())" 2>/dev/null
}

case "${1:-}" in
    has-audio)   rpc JSONRPC.Ping '{}' | grep -q pong; exit $? ;;
    volume-level) app_prop volume; exit ;;
    mute-status) case "$(app_prop muted)" in true) echo on ;; false) echo off ;; *) echo unknown ;; esac; exit ;;
    mute)        case "$2" in on) m=true ;; off) m=false ;; *) m='"toggle"' ;; esac
                 rpc Application.SetMute "{\"mute\":$m}" | ok; exit ;;
    volume)      case "$2" in
                     up|down) v=$(app_prop volume); [ -n "$v" ] || exit 1
                              [ "$2" = up ] && v=$((v + STEP)) || v=$((v - STEP)) ;;
                     *) v=$2 ;;
                 esac
                 [ "$v" -lt 0 ] && v=0; [ "$v" -gt 100 ] && v=100
                 rpc Application.SetVolume "{\"volume\":$v}" | ok; exit ;;
esac

PID=$(player_id)
[ -n "$PID" ] || exit 1
case "${1:-}" in
    active)  exit 0 ;;
    status)  case "$(rpc Player.GetProperties "{\"playerid\":$PID,\"properties\":[\"speed\"]}")" in
                 *'"speed":0'*) echo paused ;; *) echo playing ;; esac ;;
    pause)   rpc Player.PlayPause "{\"playerid\":$PID,\"play\":false}" | ok ;;
    resume)  rpc Player.PlayPause "{\"playerid\":$PID,\"play\":true}" | ok ;;
    toggle)  rpc Player.PlayPause "{\"playerid\":$PID,\"play\":\"toggle\"}" | ok ;;
    seek)    rpc Player.Seek "{\"playerid\":$PID,\"value\":{\"seconds\":${2#+}}}" | ok ;;
    stop)    rpc Player.Stop "{\"playerid\":$PID}" | ok ;;
    loop-status) case "$(rpc Player.GetProperties "{\"playerid\":$PID,\"properties\":[\"repeat\"]}")" in
                 *'"repeat":"off"'*) echo off ;; *'"repeat":'*) echo on ;; *) echo unknown ;; esac ;;
    loop)    case "$2" in
                 on)  rpc Player.SetRepeat "{\"playerid\":$PID,\"repeat\":\"one\"}" | ok ;;
                 off) rpc Player.SetRepeat "{\"playerid\":$PID,\"repeat\":\"off\"}" | ok ;;
                 *)   if [ "$("$0" loop-status)" = on ]; then "$0" loop off; else "$0" loop on; fi ;;
             esac ;;
    *)       exit 2 ;;
esac
