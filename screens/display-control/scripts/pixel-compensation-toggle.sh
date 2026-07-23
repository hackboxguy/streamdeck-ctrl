#!/bin/bash
# Toggle pixel compensation through disptool's protocol-safe FPGA auto selection.
# $1 = requested state ("on" or "off")

set -u

# The Pi image installs disptool outside the Stream Deck service's PATH.
# Keep DISPTOOL overridable for development and alternate deployments.
DISPTOOL="${DISPTOOL:-/home/pi/micropanel/bin/disptool}"
I2CDEV="${I2CDEV:-/dev/i2c-1}"
SOCK="${STREAMDECK_SOCKET:-/run/streamdeck-ctrl/notify.sock}"
STATE_FILE="${FPGA_LDPC_STATE_FILE:-/tmp/fpga-ldpc-state.json}"
LOCK_FILE="${FPGA_LDPC_LOCK_FILE:-/tmp/fpga-ldpc.lock}"

case "${1:-}" in
    on|off) STATE="$1" ;;
    *)
        echo "pixel-compensation: expected requested state 'on' or 'off'" >&2
        exit 2
        ;;
esac

if [ "$STATE" = "on" ]; then
    PREVIOUS_STATE="off"
else
    PREVIOUS_STATE="on"
fi

notify_state() {
    [ -S "$SOCK" ] || return 0
    printf '{"id":"display.pixel_compensation","state":"%s"}\n' "$1" \
        | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1 || true
}

save_requested_state() {
    python3 - "$STATE_FILE" "$STATE" <<'PY'
import json
import os
import sys
import tempfile

path, requested = sys.argv[1], sys.argv[2]
state = {
    "version": 1,
    # Existing Qt legacy clients require this value while reading the shared
    # requested-state file.  It is harmless on new FPGA targets, whose Qt
    # controllers additionally reconcile from hardware readback.
    "protocol": "legacy",
    "local_dimming": True,
    "pixel_compensation": True,
}
try:
    with open(path, "r") as existing:
        loaded = json.load(existing)
    if isinstance(loaded, dict):
        state.update(loaded)
except (OSError, ValueError, TypeError):
    pass

state["version"] = 1
state["protocol"] = "legacy"
state["local_dimming"] = bool(state.get("local_dimming", True))
state["pixel_compensation"] = requested == "on"

directory = os.path.dirname(path) or "."
fd, temporary = tempfile.mkstemp(prefix=".fpga-ldpc-", dir=directory)
try:
    with os.fdopen(fd, "w") as output:
        json.dump(state, output, separators=(",", ":"))
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
}

# Local-dimming and pixel-compensation actions run asynchronously.  The shared
# lock keeps rapid presses across both keys ordered at the FPGA.
if command -v flock >/dev/null 2>&1; then
    exec 9>"$LOCK_FILE"
    flock -x 9
fi

if ! "$DISPTOOL" --i2cdev="$I2CDEV" --device=fpgaauto \
        --command=pixelcomp --value="$STATE"; then
    echo "pixel-compensation: FPGA write failed; restoring Stream Deck icon" >&2
    notify_state "$PREVIOUS_STATE"
    exit 1
fi

if ! save_requested_state; then
    # The FPGA write succeeded, so retain the correct icon even if the
    # optional cross-UI synchronization record could not be updated.
    echo "pixel-compensation: wrote FPGA but failed to update $STATE_FILE" >&2
fi

notify_state "$STATE"
echo "pixel-compensation: $STATE"
