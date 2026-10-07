#!/bin/bash
# Toggle local dimming on the display FPGA, keeping the choice where every app
# with LD/PC buttons keeps it (fpga-ldpc-lib.sh: the file, the protocol rule).
# $1 = requested state ("on" or "off")

set -u
cd "$(dirname "$0")" || exit 1
. ./fpga-ldpc-lib.sh

case "${1:-}" in
    on|off) STATE="$1" ;;
    *)
        echo "local-dimming: expected requested state 'on' or 'off'" >&2
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
if ! set_fpga localdim "$STATE" "$DEVICE"; then
    echo "local-dimming: FPGA write failed ($DEVICE); restoring Stream Deck icon" >&2
    notify_key display.local_dimming "$PREVIOUS_STATE"
    exit 1
fi

if ! save_choice local_dimming "$STATE" "$DEVICE"; then
    # The FPGA write succeeded, so keep the icon even if the shared record
    # could not be updated.
    echo "local-dimming: wrote FPGA but failed to update $STATE_FILE" >&2
fi

notify_key display.local_dimming "$STATE"
echo "local-dimming: $STATE ($DEVICE, $STATE_FILE)"
