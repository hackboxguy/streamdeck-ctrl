#!/bin/bash
# Flash an on-board FPGA over JTAG and report the outcome back to the deck.
#
# Mirrors micropanel's "Update FPGA -> <board> -> Update" list item, which
# drives fpga-jtag-flasher-wrapper.sh. The wrapper defaults to the bitstream
# shipped on the Pi (fpga/bitbin) -- micropanel calls that the "internal"
# path, as opposed to one found on a USB stick.
#
# Usage:
#   flash-fpga.sh --id=<notification-id> --file=<bitstream-stem> \
#                 --fpga-type=xilinx|lattice [--expected-device=NAME] \
#                 [--label=<name>]
#
#   --file             bitstream base name, no extension (e.g. 12-3-inch-new)
#   --expected-device  optional guard: the flasher refuses if the detected
#                      FPGA does not match (e.g. LFE5U-25)
#
# The key that launches this is a `task` key: streamdeck-ctrl paints a blinking
# green border while this runs, and the states pushed below leave it solid
# green (success) or solid red (failure).

MICROPANEL_HOME="${MICROPANEL_HOME:-/home/pi/micropanel}"
FLASH_TOOL="$MICROPANEL_HOME/fpga/bin/fpga-jtag-flasher-wrapper.sh"

SOCK="/run/streamdeck-ctrl/notify.sock"
LOG_FILE="/tmp/fpga-flash.log"
# Shared with flash-ioc.sh on purpose. The FPGA goes over JTAG and the IOC over
# the Bluebox/UART, but both reset and drive the same target board, so only one
# programming run may be in flight at a time.
LOCK_FILE="/tmp/target-flash.lock"

NOTIFY_ID=""
FILE=""
FPGA_TYPE=""
EXPECTED_DEVICE=""
LABEL=""

for arg in "$@"; do
    case "$arg" in
        --id=*)              NOTIFY_ID="${arg#*=}" ;;
        --file=*)            FILE="${arg#*=}" ;;
        --fpga-type=*)       FPGA_TYPE="${arg#*=}" ;;
        --expected-device=*) EXPECTED_DEVICE="${arg#*=}" ;;
        --label=*)           LABEL="${arg#*=}" ;;
        *) echo "[fpga-flash] Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

[ -n "$NOTIFY_ID" ] || { echo "[fpga-flash] --id is required" >&2; exit 2; }
[ -n "$FILE" ]      || { echo "[fpga-flash] --file is required" >&2; exit 2; }
[ -n "$LABEL" ]     || LABEL="$FILE"
case "$FPGA_TYPE" in
    xilinx|lattice) ;;
    *) echo "[fpga-flash] --fpga-type must be xilinx or lattice" >&2; exit 2 ;;
esac

notify() {
    echo "{\"id\":\"$NOTIFY_ID\",\"state\":\"$1\"}" \
        | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
}

log() {
    echo "[fpga-flash/$LABEL] $*" | tee -a "$LOG_FILE"
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[fpga-flash/$LABEL] Another flash is already in progress, ignoring" >&2
    exit 0
fi

: > "$LOG_FILE"
notify running

if [ ! -x "$FLASH_TOOL" ]; then
    log "ERROR: missing $FLASH_TOOL (is micropanel installed under $MICROPANEL_HOME?)"
    notify failure
    exit 1
fi

ARGS=( --operation=flash --file="$FILE" --fpga-type="$FPGA_TYPE" )
[ -n "$EXPECTED_DEVICE" ] && ARGS+=( --expected-device="$EXPECTED_DEVICE" )

log "Flashing $LABEL FPGA with $FILE ($FPGA_TYPE)"
stdbuf -oL -eL "$FLASH_TOOL" "${ARGS[@]}" >>"$LOG_FILE" 2>&1
STATUS=$?

if [ "$STATUS" -eq 0 ]; then
    log "Flash completed successfully"
    notify success
else
    log "Flash FAILED (exit $STATUS), see $LOG_FILE"
    notify failure
fi

exit "$STATUS"
