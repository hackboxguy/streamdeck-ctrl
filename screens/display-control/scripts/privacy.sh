#!/bin/bash
# Privacy display (12.3" NQ5 privacy panel): the switchable privacy film in
# the FOG, and the privacy light, a 33-LED bar feeding a side light guide
# whose PWM level (0-100 %) hides what the film still leaks toward the driver.
#
#   privacy.sh film on|off|toggle   the Privacy key's press ({state} = the
#                                   requested state); the key's icon is put back
#                                   on any failure
#   privacy.sh film-state           "on" / "off" for the key's state_watch;
#                                   exits non-zero when it cannot be read
#   privacy.sh level up|down        Privacy Level Up/Down: +/- STEP %, clamped
#   privacy.sh level N              set the level to N % (0-100)
#   privacy.sh level                the Privacy Level key's poll: "40%", or "--"
#                                   on a display without a privacy light
#   privacy.sh level --notify       push the level to the key now
#
# Film: `disptool --device=fpganew --command=privacy [--value=on|off]`, the
# FPGA's register 0x34 bit 0 (film drive on pixelpipe v0x8B+), read back.
# Light: `disptool --device=ioc --command=privlevel [--value=0-100]`, the display
# IOC's (0x66) 0x0202/0x0203 (S4 display_manager v01.12+). The level lives in
# the MCU's RAM: 0 after every MCU reset.
#
# Only a display whose IOC runs display_manager (any variant, e.g.
# display_mgr_s4) and answers the privacy-light read is touched; anything else
# reads "--" and refuses. Nothing is sent while a flash script holds
# /tmp/target-flash.lock (the MCU may be in its bootloader or an FPGA flash).
DISPTOOL="${MICROPANEL_HOME:-/home/pi/micropanel}/bin/disptool"
SOCK="${NOTIFY_SOCK:-/run/streamdeck-ctrl/notify.sock}"
FLASH_LOCK="/tmp/target-flash.lock"
FILM_ID="display.privacy"
LEVEL_ID="display.privacy_level"
STEP=10

strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
flash_running() { [ -e "$FLASH_LOCK" ] && ! flock -n "$FLASH_LOCK" true 2>/dev/null; }
notify() {   # notify ID state|value VALUE
    [ -S "$SOCK" ] || return 0
    echo "{\"id\":\"$1\",\"$2\":\"$3\"}" | socat -t 1 - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1 || true
}

# The IOC's register reads are not atomic (address write, then a separate
# read): now and then the MCU answers 0xFF / half a value, more often while
# als-dimmer polls it too. disptool then reports "not supported" or a garbled
# string, so every read is tried up to READ_TRIES times.
READ_TRIES=3
retry() {   # retry CMD...: CMD's first non-empty output
    local i out
    for ((i = 0; i < READ_TRIES; i++)); do
        out=$("$@")
        [ -n "$out" ] && { echo "$out"; return 0; }
        sleep 0.05
    done
    return 1
}
# The level in %, or nothing when there is no privacy light to read.
read_level_once() {
    timeout 2 "$DISPTOOL" --device=ioc --command=privlevel "$@" 2>/dev/null | strip_ansi \
        | sed -n 's/^Privacy level *: *\([0-9][0-9]*\) *%.*/\1/p'
}
read_level() { retry read_level_once; }
read_film_once() {
    timeout 2 "$DISPTOOL" --device=fpganew --command=privacy "$@" 2>/dev/null | strip_ansi \
        | sed -n 's/^Privacy *: *\(on\|off\)\b.*/\1/p'
}
read_film() { retry read_film_once; }
app_once() {
    timeout 2 "$DISPTOOL" --device=ioc --command=iocversion 2>/dev/null | strip_ansi \
        | sed -n 's/^App Name *: *//p' | tr -d '[:space:]' \
        | grep -E '^(display_manager|display_mgr_[A-Za-z0-9_]+)$'
}
# A display_manager IOC (any variant) with a privacy light. The firmware name
# is cached for APP_CACHE_SEC (a new one needs an MCU flash, which holds the
# flash lock); the privacy light is read every time.
APP_CACHE="/tmp/streamdeck-privacy-app.cache"
APP_CACHE_SEC=60
supported() {
    [ -x "$DISPTOOL" ] || return 1
    flash_running && return 1
    local age
    age=$(( $(date +%s) - $(stat -c %Y "$APP_CACHE" 2>/dev/null || echo 0) ))
    if [ ! -s "$APP_CACHE" ] || [ "$age" -ge "$APP_CACHE_SEC" ] || [ "$age" -lt 0 ]; then
        retry app_once > "$APP_CACHE" || { rm -f "$APP_CACHE"; return 1; }
    fi
    [ -n "$(read_level)" ]
}

case "${1:-}" in
    film-state)
        supported || exit 1
        s=$(read_film)
        [ -n "$s" ] || exit 1
        echo "$s"
        ;;
    film)
        want="${2:-}"
        if ! supported; then
            echo "privacy: no privacy display (display_manager IOC with a privacy light) found" >&2
            [ "$want" = on ] && notify "$FILM_ID" state off
            [ "$want" = off ] && notify "$FILM_ID" state on
            exit 1
        fi
        now=$(read_film)
        case "$want" in
            toggle) [ "$now" = on ] && want=off || want=on ;;
            on|off) ;;
            *) echo "privacy: film expects on, off or toggle" >&2; exit 2 ;;
        esac
        got=$(read_film_once --value="$want")
        [ "$got" = "$want" ] || got=$(read_film)
        if [ "$got" != "$want" ]; then
            echo "privacy: film $want failed, reads '${got:-nothing}'" >&2
            notify "$FILM_ID" state "${now:-off}"
            exit 1
        fi
        notify "$FILM_ID" state "$want"
        echo "privacy: film $want"
        ;;
    level)
        arg="${2:-}"
        if [ -z "$arg" ] || [ "$arg" = --notify ]; then
            v=--
            supported && v="$(read_level)%"
            [ "$v" = "%" ] && v=--
            if [ "$arg" = --notify ]; then notify "$LEVEL_ID" value "$v"; else echo "$v"; fi
            exit 0
        fi
        supported || { echo "privacy: no privacy light found" >&2; exit 1; }
        cur=$(read_level) || { echo "privacy: cannot read the privacy light level" >&2; exit 1; }
        case "$arg" in
            up) new=$(( cur + STEP )) ;;
            down) new=$(( cur - STEP )) ;;
            *[!0-9]*) echo "privacy: level expects up, down or 0-100" >&2; exit 2 ;;
            *) new=$arg ;;
        esac
        [ "$new" -gt 100 ] && new=100
        [ "$new" -lt 0 ] && new=0
        got=$(read_level_once --value="$new")
        [ "$got" = "$new" ] || got=$(read_level)
        notify "$LEVEL_ID" value "${got:---}${got:+%}"
        if [ "$got" != "$new" ]; then
            echo "privacy: level $new failed, reads '${got:-nothing}'" >&2
            exit 1
        fi
        echo "privacy: level $new%"
        ;;
    *)
        echo "usage: privacy.sh film on|off|toggle | film-state | level [up|down|N|--notify]" >&2
        exit 2
        ;;
esac
