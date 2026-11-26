#!/bin/bash
# Choose who feeds the remote display: the Pi (its HDMI) or an external PC (its
# DP output into the 983, with the Pi's USB-C port as the PC's touch + display
# control link). The PC Source key's press and state.
#
#   pc-source.sh on|off   the key's press ({state} = requested state):
#                         on = external PC (USB bridge), off = the Pi
#   pc-source.sh state    print "on" / "off"
#
# fpd-bridge-mode.sh (br-wrapper fpd-hid-bridge) does the work and stores the
# mode on the data partition, so it holds across reboots. In PC mode the Pi's
# launcher does not run: keys that start Pi apps have nothing to start until
# the key is switched off again. The video cable itself is not switched: plug
# the PC's DP (or the Pi's HDMI adapter) into the 983 to match.

MODE_TOOL="${MICROPANEL_HOME:-/home/pi/micropanel}/bin/fpd-bridge-mode.sh"
SOCK="/run/streamdeck-ctrl/notify.sock"
NOTIFY_ID="display.pc_source"

notify_key() {
    [ -S "$SOCK" ] || return 0
    echo "{\"id\":\"$NOTIFY_ID\",\"state\":\"$1\"}" \
        | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
}

read_state() {
    case "$("$MODE_TOOL" get 2>/dev/null)" in
        external) echo on ;;
        pi) echo off ;;
    esac
}

case "${1:-}" in
    state)
        [ -x "$MODE_TOOL" ] || exit 1
        s=$(read_state)
        [ -n "$s" ] || exit 1
        echo "$s"
        exit 0
        ;;
    on) WANT=on; MODE=external; PREVIOUS=off ;;
    off) WANT=off; MODE=pi; PREVIOUS=on ;;
    *) echo "pc-source: expected on, off or state" >&2; exit 2 ;;
esac

# The key has already flipped its icon; put it back on any refusal.
if [ ! -x "$MODE_TOOL" ]; then
    echo "pc-source: $MODE_TOOL not found (image without fpd-hid-bridge)" >&2
    notify_key "$PREVIOUS"
    exit 1
fi

if ! sudo -n "$MODE_TOOL" set "$MODE" >/dev/null; then
    echo "pc-source: fpd-bridge-mode.sh set $MODE failed" >&2
fi

s=$(read_state)
notify_key "${s:-$PREVIOUS}"
if [ "$s" != "$WANT" ]; then
    echo "pc-source: asked for $WANT, the mode is '${s:-unknown}'" >&2
    exit 1
fi
echo "pc-source: $WANT ($MODE)"
