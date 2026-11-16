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
# als-dimmer owns both settings: it saves them (/data/als-dimmer/state.json),
# restores them after a reboot or an FPGA/IOC restart, and every 5 s writes
# the saved value back over anything else in the hardware. So everything goes
# through als-dimmer-client (--privacy, --privacy-level), never disptool:
# a direct write would be undone within seconds. als-dimmer decides whether
# the display has the film / the light and answers "--" when not. Changes made
# elsewhere (Display Settings, als-dimmer's startup) reach the keys through
# als-dimmer-notify.sh (privacy_changed, privacy_level_changed).
SOCK="${NOTIFY_SOCK:-/run/streamdeck-ctrl/notify.sock}"
FILM_ID="display.privacy"
LEVEL_ID="display.privacy_level"
STEP=10

for c in /home/pi/als-dimmer/bin/als-dimmer-client /usr/bin/als-dimmer-client; do
    [ -x "$c" ] && CLIENT="$c" && break
done

notify() {   # notify ID state|value VALUE
    [ -S "$SOCK" ] || return 0
    echo "{\"id\":\"$1\",\"$2\":\"$3\"}" | socat -t 1 - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1 || true
}
# als-dimmer-client ARG: its one-line answer; bounded, as the key polls must
# not hang on a daemon that accepts but never answers. An als-dimmer without
# privacy support (older image) prints its usage and fails: nothing.
client() {
    [ -n "$CLIENT" ] || return 1
    local out
    out=$(timeout 3 "$CLIENT" "$1" 2>/dev/null) || return 1
    echo "$out" | head -n 1 | tr -d '[:space:]'
}
film() { client --privacy${1:+=$1} | grep -xE 'on|off'; }
level() { client --privacy-level${1:+=$1} | grep -xE '[0-9]{1,3}'; }

case "${1:-}" in
    film-state)
        film || exit 1
        ;;
    film)
        want="${2:-}"
        case "$want" in
            on|off|toggle) ;;
            *) echo "privacy: film expects on, off or toggle" >&2; exit 2 ;;
        esac
        if ! got=$(film "$want"); then
            echo "privacy: als-dimmer did not switch the privacy film (no film on this display?)" >&2
            # put the key back to what the display holds
            now=$(film) || now=$([ "$want" = on ] && echo off || echo on)
            notify "$FILM_ID" state "$now"
            exit 1
        fi
        notify "$FILM_ID" state "$got"
        echo "privacy: film $got"
        ;;
    level)
        arg="${2:-}"
        if [ -z "$arg" ] || [ "$arg" = --notify ]; then
            v=$(level) && v="$v%" || v=--
            if [ "$arg" = --notify ]; then notify "$LEVEL_ID" value "$v"; else echo "$v"; fi
            exit 0
        fi
        case "$arg" in
            up) req="+$STEP" ;;
            down) req="-$STEP" ;;
            *[!0-9]*) echo "privacy: level expects up, down or 0-100" >&2; exit 2 ;;
            *) req="$arg" ;;
        esac
        if ! got=$(level "$req"); then
            echo "privacy: als-dimmer did not set the privacy light (no light on this display?)" >&2
            exit 1
        fi
        notify "$LEVEL_ID" value "$got%"
        echo "privacy: level $got%"
        ;;
    *)
        echo "usage: privacy.sh film on|off|toggle | film-state | level [up|down|N|--notify]" >&2
        exit 2
        ;;
esac
