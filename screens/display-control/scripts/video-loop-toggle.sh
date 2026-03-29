#!/bin/bash
# Toggle Kodi video loop via JSON-RPC
# $1 = new state ("on" or "off")
KODI="http://127.0.0.1:8080/jsonrpc"

if [ "$1" = "on" ]; then
    REPEAT="one"
else
    REPEAT="off"
fi

curl -s "$KODI" -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"method\":\"Player.SetRepeat\",\"params\":{\"playerid\":1,\"repeat\":\"$REPEAT\"},\"id\":1}" \
    --connect-timeout 2 > /dev/null 2>&1
