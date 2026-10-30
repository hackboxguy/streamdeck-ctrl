#!/bin/bash
# Print the display brightness als-dimmer holds, as "N%", or "--" when no
# als-dimmer answers (e.g. an HDMI monitor without an ambient sensor, where no
# daemon runs). Display-agnostic: it asks the daemon, whatever its output is.
#
# Used two ways:
#   - polled by streamdeck-ctrl (live.poll_command), as the safety net that
#     also catches changes made elsewhere (disp-settings, ALS in AUTO mode)
#   - "--notify": push the value to the deck at once, called by
#     brightness-up.sh / brightness-down.sh right after they set it

SOCK="/run/streamdeck-ctrl/notify.sock"

for c in /home/pi/als-dimmer/bin/als-dimmer-client /usr/bin/als-dimmer-client; do
    [ -x "$c" ] && ALS_CLIENT="$c" && break
done

VALUE="--"
if [ -n "$ALS_CLIENT" ]; then
    # Bounded: a daemon that accepts but never answers would otherwise hang the
    # client, and the poll's own timeout kills only the shell, orphaning it.
    CURRENT=$(timeout 2 "$ALS_CLIENT" --brightness 2>/dev/null)
    [[ "$CURRENT" =~ ^[0-9]+$ ]] && VALUE="${CURRENT}%"
fi

if [ "$1" = "--notify" ]; then
    [ -S "$SOCK" ] || exit 0   # deck not running; the poll will catch up
    echo "{\"id\":\"display.brightness\",\"value\":\"$VALUE\"}" \
        | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
    exit 0
fi

echo "$VALUE"
