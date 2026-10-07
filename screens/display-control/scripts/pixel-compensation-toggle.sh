#!/bin/bash
# Toggle pixel compensation on the display FPGA, keeping the choice where every app
# with LD/PC buttons keeps it (fpga-ldpc-lib.sh: the file, the protocol rule).
# $1 = requested state ("on" or "off")

set -u
cd "$(dirname "$0")" || exit 1
. ./fpga-ldpc-lib.sh

case "${1:-}" in
    on|off) STATE="$1" ;;
    *)
        echo "pixel-compensation: expected requested state 'on' or 'off'" >&2
        exit 2
        ;;
esac
PREVIOUS_STATE=$([ "$STATE" = on ] && echo off || echo on)

# Action scripts run asynchronously; the shared lock keeps rapid presses
# across both keys ordered at the FPGA. flock is on the Pi target; continue
# safely if a minimal image does not provide it.
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_FILE"
    flock -x 9
fi

DEVICE=$(fpga_device)
if ! set_fpga pixelcomp "$STATE" "$DEVICE"; then
    echo "pixel-compensation: FPGA write failed ($DEVICE); restoring Stream Deck icon" >&2
    notify_key display.pixel_compensation "$PREVIOUS_STATE"
    exit 1
fi

if ! save_choice pixel_compensation "$STATE" "$DEVICE"; then
    # The FPGA write succeeded, so keep the icon even if the shared record
    # could not be updated.
    echo "pixel-compensation: wrote FPGA but failed to update $STATE_FILE" >&2
fi

notify_key display.pixel_compensation "$STATE"
echo "pixel-compensation: $STATE ($DEVICE, $STATE_FILE)"
