#!/bin/bash
# Flash the 17" OLED-IB's touch controller (Himax HX8530) and reboot the Pi.
#
# The image comes from the sp6bins tree micropanel installs. The himax_oledib
# driver programs it itself: it is handed a firmware *name*, which the kernel
# looks up under /lib/firmware, so the image is first copied there. The Pi's
# root is an overlayroot, so that copy lands in RAM and is gone after the
# reboot, which is what we want.
#
# Usage:
#   flash-touch.sh --id=<notification-id> --firmware=<file> [--label=<name>]
#
#   --firmware  filename under $SP6BINS/firmware/touch, or an absolute path
#
# A `task` key launches this: the border blinks green while it runs. On
# success the key turns solid green and the Pi reboots a few seconds later;
# the touch driver switches sensing back on when it probes. On failure the key
# turns solid red and the Pi does NOT reboot, so the operator sees it; the
# log is in $LOG_FILE.

MICROPANEL_HOME="${MICROPANEL_HOME:-/home/pi/micropanel}"
SP6BINS="$MICROPANEL_HOME/share/sp6bins"
DEBUG_NODE="/proc/android_touch/debug"
DRIVER="himax_oledib"
REBOOT_DELAY_SEC=5
LAUNCHER="$MICROPANEL_HOME/usr/bin/launcher-client"
LAUNCHER_SRV="127.0.0.1:8081"

SOCK="/run/streamdeck-ctrl/notify.sock"
LOG_FILE="/tmp/touch-flash.log"
# The same lock as flash-ioc.sh and flash-fpga.sh: one programming run on the
# target board at a time.
LOCK_FILE="/tmp/target-flash.lock"

NOTIFY_ID=""
FIRMWARE=""
LABEL=""

for arg in "$@"; do
    case "$arg" in
        --id=*)       NOTIFY_ID="${arg#*=}" ;;
        --firmware=*) FIRMWARE="${arg#*=}" ;;
        --label=*)    LABEL="${arg#*=}" ;;
        *) echo "[touch-flash] Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

[ -n "$NOTIFY_ID" ] || { echo "[touch-flash] --id is required" >&2; exit 2; }
[ -n "$FIRMWARE" ]  || { echo "[touch-flash] --firmware is required" >&2; exit 2; }
[ -n "$LABEL" ]     || LABEL="touch"

# Bare filenames resolve inside the installed sp6bins tree.
case "$FIRMWARE" in /*) ;; *) FIRMWARE="$SP6BINS/firmware/touch/$FIRMWARE" ;; esac
FW_NAME="$(basename "$FIRMWARE")"

notify() {
    echo "{\"id\":\"$NOTIFY_ID\",\"state\":\"$1\"}" \
        | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
}

log() {
    echo "[touch-flash/$LABEL] $*" | tee -a "$LOG_FILE"
}

fail() {
    log "ERROR: $*"
    notify failure
    exit 1
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[touch-flash/$LABEL] Another flash is already in progress, ignoring" >&2
    exit 0
fi

: > "$LOG_FILE"
notify running

[ -r "$FIRMWARE" ] || fail "missing $FIRMWARE (is sp6bins installed under $SP6BINS?)"

# himax_oledib is only loaded for the oled-ib-17 display type, so this also
# keeps the key from doing anything on another rig.
grep -q "^$DRIVER " /proc/modules \
    || fail "$DRIVER is not loaded: not an OLED-IB rig, or the touch driver failed to probe (see dmesg)"
[ -e "$DEBUG_NODE" ] || fail "$DEBUG_NODE missing: $DRIVER was built without its debug node"

# Nothing else may talk to the chip while it is programmed. In this driver
# even *reading* /proc/android_touch/vendor resets the chip, and disp-settings
# reads it every 10 s for its touch info card: that broke a flash with
# "Check WEL Fail" on all three of the driver's tries. Go back to the
# launcher's home, which stops whichever app is running.
RUNNING=$("$LAUNCHER" --srv="$LAUNCHER_SRV" --command=get-running-app 2>/dev/null)
if [ -n "$RUNNING" ] && [ "$RUNNING" != "none" ]; then
    log "Stopping $RUNNING first"
    "$LAUNCHER" --srv="$LAUNCHER_SRV" --command=stop-app >/dev/null 2>&1
fi
for i in 1 2 3 4 5; do
    pgrep -x disp-settings >/dev/null || break
    [ "$i" -eq 3 ] && pkill -x disp-settings
    sleep 1
done
pgrep -x disp-settings >/dev/null && fail "disp-settings is still running; it resets the touch chip every 10 s"

sudo install -m 0644 "$FIRMWARE" "/lib/firmware/$FW_NAME" \
    || fail "cannot copy $FW_NAME to /lib/firmware"

log "Flashing $FW_NAME ($(md5sum < "$FIRMWARE" | cut -d' ' -f1)), about 25 s"
START=$(date +%s)
# The write returns once the driver has programmed and CRC-checked the flash.
printf 't %s\n' "$FW_NAME" | sudo tee "$DEBUG_NODE" >/dev/null
RESULT=$(sudo cat "$DEBUG_NODE" 2>/dev/null | tr -d '\0' | grep -m1 "FW Update")
log "Driver: ${RESULT:-no result} after $(( $(date +%s) - START )) s"
sudo dmesg | grep -i "HXTP" | tail -n 20 >>"$LOG_FILE"

sudo rm -f "/lib/firmware/$FW_NAME"

case "$RESULT" in
    *"FW Update-Complete"*) ;;
    *) fail "flash FAILED, see $LOG_FILE; not rebooting" ;;
esac

log "Flash completed successfully, rebooting in $REBOOT_DELAY_SEC s"
notify success
sync
sleep "$REBOOT_DELAY_SEC"
sudo systemctl reboot
exit 0
