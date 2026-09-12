#!/bin/bash
# Flash the 983HH board's RH850 IOC and report the outcome back to the deck.
#
# Mirrors the micropanel "IOC-Update -> 983HHV3 -> Update" list item:
#   rh850-flash-auto.sh --board=983hh --npj=983HH.npj \
#       --bios-autorun=983HH_983_manager.bin
#
# Transport is chosen by rh850-flash-auto.sh, not here: when an EEHB Bluebox
# dongle (USB 0403:a9a0) is plugged into the Pi it programs over the Bluebox's
# two serial interfaces, otherwise it falls back to the Pi's GPIO/UART wiring.
# So the operator only has to attach the dongle and press the key.
#
# The key is a `task` key: streamdeck-ctrl paints a blinking green border while
# this script runs, and the states pushed below leave it solid green (success)
# or solid red (failure).

MICROPANEL_HOME="${MICROPANEL_HOME:-/home/pi/micropanel}"
FLASH_TOOL="$MICROPANEL_HOME/bin/rh850-flash-auto.sh"
NPJ="$MICROPANEL_HOME/share/sp6bins/config/983HH.npj"
FIRMWARE="$MICROPANEL_HOME/share/sp6bins/firmware/bios-bin/983HH_983_manager.bin"

SOCK="/run/streamdeck-ctrl/notify.sock"
NOTIFY_ID="ioc.flash_983hh"
LOG_FILE="/tmp/983hh-ioc-flash.log"
LOCK_FILE="/tmp/983hh-ioc-flash.lock"

notify() {
    echo "{\"id\":\"$NOTIFY_ID\",\"state\":\"$1\"}" \
        | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
}

log() {
    echo "[983hh-ioc-flash] $*" | tee -a "$LOG_FILE"
}

# One flash at a time. streamdeck-ctrl already swallows presses while the key
# is running; this also covers the script being started from somewhere else.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[983hh-ioc-flash] Another flash is already in progress, ignoring" >&2
    exit 0
fi

: > "$LOG_FILE"
notify running

for f in "$FLASH_TOOL" "$NPJ" "$FIRMWARE"; do
    if [ ! -r "$f" ]; then
        log "ERROR: missing $f (is micropanel installed under $MICROPANEL_HOME?)"
        notify failure
        exit 1
    fi
done

log "Flashing 983HH IOC with $(basename "$FIRMWARE")"
stdbuf -oL -eL "$FLASH_TOOL" \
    --board=983hh \
    --npj="$NPJ" \
    --bios-autorun="$FIRMWARE" >>"$LOG_FILE" 2>&1
STATUS=$?

if [ "$STATUS" -eq 0 ]; then
    log "Flash completed successfully"
    notify success
else
    log "Flash FAILED (exit $STATUS), see $LOG_FILE"
    notify failure
fi

exit "$STATUS"
