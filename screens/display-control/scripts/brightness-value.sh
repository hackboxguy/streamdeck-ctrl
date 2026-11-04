#!/bin/bash
# Print the display brightness als-dimmer holds, followed by the display's
# backlight temperature when its IOC reports one: "30% 32°C" (the key wraps
# it onto two lines), "30%" without a temperature, or "--" when no als-dimmer
# answers (e.g. an HDMI monitor without an ambient sensor, where no daemon
# runs). Display-agnostic: it asks the daemon, whatever its output is.
#
# Used two ways:
#   - polled by streamdeck-ctrl (live.poll_command), as the safety net that
#     also catches changes made elsewhere (disp-settings, ALS in AUTO mode)
#   - "--notify": push the value to the deck at once, called by
#     brightness-up.sh / brightness-down.sh right after they set it
#
# Backlight temperature: the same reading the disp-settings app shows, the
# display IOC's (0x66) shared rows 0x1000..0x1003 via `disptool --device=ioc
# --command=bltemp` (one atomic I2C write+read, as als-dimmer polls the same
# MCU). On QVUE_9090 display_manager v01.04+ it is the backlight unit's
# thermistor, the main-PCB NTC before that. Shown only when the IOC runs
# display_manager (OTS-OLED, LAT45, S7, 3x QVue): a board with no answer on
# 0x66 (HDMI monitor, stock QVue firmware), qvue_legacy, an uncalibrated
# sensor (0x8000) or an implausible value shows brightness only. Only 0x66 is
# ever read: a read of 0x32 hangs the stock QVue firmware.
#
# Temperature changes slowly, so it is read at most every BLTEMP_MAX_AGE_SEC
# and cached; brightness stays live on every call. No reads while a flash
# script holds the target lock (the MCU may be in its bootloader, or busy
# with an FPGA flash session).

SOCK="/run/streamdeck-ctrl/notify.sock"
DISPTOOL="${MICROPANEL_HOME:-/home/pi/micropanel}/bin/disptool"
BLTEMP_CACHE="/tmp/streamdeck-bltemp.cache"
BLTEMP_MAX_AGE_SEC=10
FLASH_LOCK="/tmp/target-flash.lock"

for c in /home/pi/als-dimmer/bin/als-dimmer-client /usr/bin/als-dimmer-client; do
    [ -x "$c" ] && ALS_CLIENT="$c" && break
done

strip_ansi() {
    sed 's/\x1b\[[0-9;]*m//g'
}

# Read the IOC now: prints e.g. "32°C", or nothing.
read_bltemp() {
    [ -x "$DISPTOOL" ] || return 0
    local app t
    app=$(timeout 2 "$DISPTOOL" --device=ioc --command=iocversion 2>/dev/null \
          | strip_ansi | sed -n 's/^App Name *: *//p' | tr -d '[:space:]')
    [ "$app" = display_manager ] || return 0
    t=$(timeout 2 "$DISPTOOL" --device=ioc --command=bltemp 2>/dev/null \
        | strip_ansi | sed -n 's/^Temperature: *\(-\{0,1\}[0-9][0-9]*\.[0-9]\) C.*/\1/p')
    [ -n "$t" ] || return 0   # no answer, or "uncalibrated on this board"
    awk -v t="$t" 'BEGIN { if (t >= -40 && t <= 125) printf "%d°C\n", (t < 0 ? t - 0.5 : t + 0.5) }'
}

# The cached temperature, refreshed when older than BLTEMP_MAX_AGE_SEC.
bltemp() {
    local now age
    now=$(date +%s)
    if [ -f "$BLTEMP_CACHE" ]; then
        age=$(( now - $(stat -c %Y "$BLTEMP_CACHE" 2>/dev/null || echo 0) ))
        if [ "$age" -ge 0 ] && [ "$age" -lt "$BLTEMP_MAX_AGE_SEC" ]; then
            cat "$BLTEMP_CACHE"
            return
        fi
    fi
    # A flash in progress: show no temperature rather than touch the MCU.
    if [ -e "$FLASH_LOCK" ] && ! flock -n "$FLASH_LOCK" true 2>/dev/null; then
        rm -f "$BLTEMP_CACHE"
        return
    fi
    local t tmp
    t=$(read_bltemp)
    tmp=$(mktemp "$BLTEMP_CACHE.XXXXXX" 2>/dev/null) || { echo "$t"; return; }
    printf '%s\n' "$t" > "$tmp" && mv -f "$tmp" "$BLTEMP_CACHE"
    echo "$t"
}

VALUE="--"
if [ -n "$ALS_CLIENT" ]; then
    # Bounded: a daemon that accepts but never answers would otherwise hang the
    # client, and the poll's own timeout kills only the shell, orphaning it.
    CURRENT=$(timeout 2 "$ALS_CLIENT" --brightness 2>/dev/null)
    [[ "$CURRENT" =~ ^[0-9]+$ ]] && VALUE="${CURRENT}%"
fi

TEMP=$(bltemp)
[ -n "$TEMP" ] && VALUE="$VALUE $TEMP"

if [ "$1" = "--notify" ]; then
    [ -S "$SOCK" ] || exit 0   # deck not running; the poll will catch up
    echo "{\"id\":\"display.brightness\",\"value\":\"$VALUE\"}" \
        | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
    exit 0
fi

echo "$VALUE"
