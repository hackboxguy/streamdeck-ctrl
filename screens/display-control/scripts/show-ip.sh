#!/bin/bash
# Print the Pi's primary IPv4 for the Stream Deck's IP key, or "No IP!".
#
# Used two ways:
#   - polled by streamdeck-ctrl (live.poll_command), as the safety net
#   - called by ip-change-notify.sh on a NetworkManager event, for an
#     immediate update
#
# "Primary" means the address on the default-route interface, so a Pi with
# both eth0 and wlan0 reports the one traffic actually leaves by. Falls back
# to the first global IPv4 when there is no default route.

primary_ip() {
    local dev
    dev=$(ip -4 route show default 2>/dev/null | awk '{print $5; exit}')
    if [ -n "$dev" ]; then
        ip -4 -o addr show dev "$dev" scope global 2>/dev/null \
            | awk '{split($4, a, "/"); print a[1]; exit}'
    fi
}

any_ip() {
    ip -4 -o addr show scope global 2>/dev/null \
        | awk '{split($4, a, "/"); print a[1]; exit}'
}

IP="$(primary_ip)"
[ -n "$IP" ] || IP="$(any_ip)"
[ -n "$IP" ] || IP="No IP!"

printf '%s\n' "$IP"
