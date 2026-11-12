#!/bin/bash
# Switch the remote display on or off through its IOC, and report its state.
#
#   display-power.sh on|off   the Display key's press ({state} = requested state)
#   display-power.sh state    print "on" / "off" for the key's state_watch;
#                             exits non-zero (the key stays as it is) when the
#                             state cannot be read
#
# `disptool --device=ioc --command=disppower --value=on|off` writes 0x01/0x00
# to the display IOC's (0x66) DISP_POWER register 0x0200; without a value it
# reads the register back. The IOC switches the panel off and on itself; the
# FPGA and the FPD-Link stay up. Every board running display_manager has it
# (OTS-OLED, LAT45, S7, 3x QVue); firmware too old to report its App Name
# (v01.14) is accepted when the DISP_POWER register reads back. Anything else (no answer on 0x66: an HDMI
# monitor, stock QVue firmware; qvue_legacy) is refused, and the key's icon
# goes back. Only 0x66 is used: a read of 0x32 hangs the stock QVue firmware.
#
# Nothing is sent while a flash script holds /tmp/target-flash.lock (the MCU
# may be in its bootloader or in an FPGA flash session).

DISPTOOL="${MICROPANEL_HOME:-/home/pi/micropanel}/bin/disptool"
SOCK="/run/streamdeck-ctrl/notify.sock"
FLASH_LOCK="/tmp/target-flash.lock"
NOTIFY_ID="display.power"

strip_ansi() {
    sed 's/\x1b\[[0-9;]*m//g'
}

flash_running() {
    [ -e "$FLASH_LOCK" ] && ! flock -n "$FLASH_LOCK" true 2>/dev/null
}

# Prints "on" / "off", or nothing when the read fails.
read_state() {
    timeout 2 "$DISPTOOL" --device=ioc --command=disppower 2>/dev/null | strip_ansi \
        | sed -n 's/^Display Power: *\(ON\|OFF\).*/\1/p' | tr '[:upper:]' '[:lower:]'
}

# display_manager by name. Firmware older than the App Name field (v01.14
# answers "not served by this firmware") counts when DISP_POWER reads back.
is_display_manager() {
    local app
    app=$(timeout 2 "$DISPTOOL" --device=ioc --command=iocversion 2>/dev/null \
          | strip_ansi | sed -n 's/^App Name *: *//p' | tr -d '[:space:]')
    case "$app" in
        display_manager) return 0 ;;
        notservedbythisfirmware) [ -n "$(read_state)" ] ;;
        *) return 1 ;;
    esac
}

notify_key() {
    [ -S "$SOCK" ] || return 0
    echo "{\"id\":\"$NOTIFY_ID\",\"state\":\"$1\"}" \
        | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
}

[ -x "$DISPTOOL" ] || { echo "display-power: $DISPTOOL not found" >&2; exit 1; }

case "${1:-}" in
    state)
        flash_running && exit 1
        is_display_manager || exit 1
        s=$(read_state)
        [ -n "$s" ] || exit 1
        echo "$s"
        exit 0
        ;;
    on|off) WANT="$1" ;;
    *) echo "display-power: expected on, off or state" >&2; exit 2 ;;
esac

PREVIOUS=$([ "$WANT" = on ] && echo off || echo on)

# The key has already flipped its icon; put it back on any refusal.
refuse() {
    echo "display-power: $*" >&2
    notify_key "$PREVIOUS"
    exit 1
}

flash_running && refuse "a flash is in progress, not touching the display"
is_display_manager || refuse "the display IOC does not run display_manager (no 0x66 DISP_POWER)"

timeout 3 "$DISPTOOL" --device=ioc --command=disppower --value="$WANT" >/dev/null 2>&1 \
    || refuse "disppower --value=$WANT failed"

# Confirm from the register, not from the write's exit status.
for _ in 1 2 3 4 5; do
    s=$(read_state)
    [ "$s" = "$WANT" ] && break
    sleep 0.3
done
if [ "$s" != "$WANT" ]; then
    notify_key "${s:-$PREVIOUS}"
    echo "display-power: wrote $WANT, the IOC reports '${s:-nothing}'" >&2
    exit 1
fi

notify_key "$WANT"
echo "display-power: $WANT"
