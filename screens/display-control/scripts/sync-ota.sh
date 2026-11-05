#!/bin/bash
# Run by streamdeck-ctrl.service after start-up (ExecStartPost runs every
# sync-*.sh): sets the page-6 OTA keys and keeps OTA-System current. Returns
# at once; the work runs in the background inside the service (its cgroup),
# so a stop or restart of the deck ends it too.
#
#   firmware + fpga  checked at start-up, retried every 30 s until each gives
#                    an answer (the 983 link and the QVue come up after the
#                    deck), then left alone: the images on the SD card do not
#                    change at run time, and the flash keys re-check when
#                    they change a board.
#   system           checked at start-up and whenever the block-device
#                    inventory changes (a USB stick in or out): lsblk every
#                    3 s, the fingerprint System Manager uses, no I2C.

HERE=$(cd -- "$(dirname -- "$0")" && pwd)
CHECK="$HERE/ota-check.sh"
LOG=/tmp/ota-check.log
[ -x "$CHECK" ] || exit 0

(
    : > "$LOG"
    sleep 5
    for _ in $(seq 1 20); do                      # up to 10 minutes
        "$CHECK" firmware fpga >>"$LOG" 2>&1 && break
        sleep 30
    done
) </dev/null >/dev/null 2>&1 &

(
    last=""
    while :; do
        now=$(lsblk -P -o PATH,TYPE,TRAN,FSTYPE 2>/dev/null)
        if [ "$now" != "$last" ]; then
            last=$now
            sleep 2                               # let a stick settle
            for _ in 1 2 3; do
                "$CHECK" system >>"$LOG" 2>&1 && break
                sleep 10
            done
        fi
        sleep 3
    done
) </dev/null >/dev/null 2>&1 &

exit 0
