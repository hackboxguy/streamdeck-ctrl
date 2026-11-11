#!/bin/bash
# Kodi (the launcher's Media Player): JSON-RPC on :8080. Stop ends playback;
# Kodi itself stays open (Home closes it).
KODI="${KODI_URL:-http://127.0.0.1:8080/jsonrpc}"
rpc() {   # rpc METHOD PARAMS-JSON -> the reply
    curl -s --connect-timeout 1 -m 3 -H 'Content-Type: application/json' \
        -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":$2}" "$KODI"
}
# the active player's id (video before audio before pictures)
PID=$(rpc Player.GetActivePlayers '{}' | python3 -c '
import json, sys
try:
    players = json.load(sys.stdin).get("result") or []
except ValueError:
    players = []
order = {"video": 0, "audio": 1, "picture": 2}
players.sort(key=lambda p: order.get(p.get("type"), 3))
print(players[0]["playerid"] if players else "")' 2>/dev/null)
[ -n "$PID" ] || exit 1
ok() { grep -q '"result"'; }
case "${1:-}" in
    active)  exit 0 ;;
    status)  case "$(rpc Player.GetProperties "{\"playerid\":$PID,\"properties\":[\"speed\"]}")" in
                 *'"speed":0'*) echo paused ;; *) echo playing ;; esac ;;
    pause)   rpc Player.PlayPause "{\"playerid\":$PID,\"play\":false}" | ok ;;
    resume)  rpc Player.PlayPause "{\"playerid\":$PID,\"play\":true}" | ok ;;
    toggle)  rpc Player.PlayPause "{\"playerid\":$PID,\"play\":\"toggle\"}" | ok ;;
    seek)    rpc Player.Seek "{\"playerid\":$PID,\"value\":{\"seconds\":${2#+}}}" | ok ;;
    stop)    rpc Player.Stop "{\"playerid\":$PID}" | ok ;;
    *)       exit 2 ;;
esac
