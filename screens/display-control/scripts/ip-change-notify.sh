#!/bin/bash
# NetworkManager dispatcher hook: push the Pi's IP to the deck the moment it
# changes, instead of waiting for the next poll.
#
# Install (as root):
#   ln -sf /home/pi/streamdeck-ctrl/screens/display-control/scripts/ip-change-notify.sh \
#          /etc/NetworkManager/dispatcher.d/90-streamdeck-ip
#
# NM calls dispatcher scripts as: $1=interface $2=action. They must be
# root-owned and executable, or NM ignores them silently.
#
# The key also polls, so this hook is an optimisation, not a dependency: drop
# it and the IP still refreshes, just on the poll interval instead of at once.

ACTION="$2"
case "$ACTION" in
    up|down|dhcp4-change|dhcp6-change|connectivity-change) ;;
    *) exit 0 ;;
esac

SOCK="/run/streamdeck-ctrl/notify.sock"
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

[ -S "$SOCK" ] || exit 0   # deck not running; the poll will catch up

VALUE="$("$SCRIPT_DIR/show-ip.sh")"
echo "{\"id\":\"system.ip\",\"value\":\"$VALUE\"}" \
    | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null

exit 0
