#!/bin/bash
# Flash an IOC (RH850) and report the outcome back to the deck.
#
# Drives micropanel's rh850-flash-auto.sh, which picks the transport itself:
# an EEHB Bluebox dongle (USB 0403:a9a0) when one is attached, the Pi's
# GPIO/UART wiring otherwise. So the operator attaches the dongle and presses
# the key. With no dongle, --board=lattice45-9090 --npj=LAT-ECP5.npj is
# handed straight to flashrh850.sh unchanged.
#
# Usage:
#   flash-ioc.sh --id=<notification-id> --board=<board> --firmware=<file> \
#                [--npj=<file>] [--label=<name>] [--expect-app=<name>]
#
#   --firmware  filename under $SP6BINS/firmware/bios-bin, or an absolute path
#   --npj       filename under $SP6BINS/config, or an absolute path. Omit for
#               boards the flasher drives without one (spartan7-9090, qvue-9090).
#   --expect-app  after a successful flash, wait for the IOC to boot and
#               require `disptool --device=ioc --command=iocversion` to report
#               this App Name (read over 0x66); otherwise the key goes red.
#
# The keys that launch this are `task` keys: streamdeck-ctrl paints a blinking
# green border while this runs, and the states pushed below leave it solid
# green (success) or solid red (failure).

MICROPANEL_HOME="${MICROPANEL_HOME:-/home/pi/micropanel}"
FLASH_TOOL="$MICROPANEL_HOME/bin/rh850-flash-auto.sh"
DISPTOOL="$MICROPANEL_HOME/bin/disptool"
# How long the freshly flashed IOC gets to boot and answer on 0x66.
APP_CHECK_TIMEOUT_SEC=20
SP6BINS="$MICROPANEL_HOME/share/sp6bins"

SOCK="/run/streamdeck-ctrl/notify.sock"
LOG_FILE="/tmp/ioc-flash.log"
# One lock for every board, shared with flash-fpga.sh: the IOCs all program
# over the same Bluebox/UART port, and an FPGA JTAG run drives the same target
# board, so only one programming run may be in flight at a time.
LOCK_FILE="/tmp/target-flash.lock"

NOTIFY_ID=""
BOARD=""
FIRMWARE=""
NPJ=""
LABEL=""
EXPECT_APP=""

for arg in "$@"; do
    case "$arg" in
        --id=*)       NOTIFY_ID="${arg#*=}" ;;
        --board=*)    BOARD="${arg#*=}" ;;
        --firmware=*) FIRMWARE="${arg#*=}" ;;
        --npj=*)      NPJ="${arg#*=}" ;;
        --label=*)    LABEL="${arg#*=}" ;;
        --expect-app=*) EXPECT_APP="${arg#*=}" ;;
        *) echo "[ioc-flash] Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

[ -n "$NOTIFY_ID" ] || { echo "[ioc-flash] --id is required" >&2; exit 2; }
[ -n "$BOARD" ]     || { echo "[ioc-flash] --board is required" >&2; exit 2; }
[ -n "$FIRMWARE" ]  || { echo "[ioc-flash] --firmware is required" >&2; exit 2; }
[ -n "$LABEL" ]     || LABEL="$BOARD"

# Bare filenames resolve inside the installed sp6bins tree.
case "$FIRMWARE" in /*) ;; *) FIRMWARE="$SP6BINS/firmware/bios-bin/$FIRMWARE" ;; esac
[ -n "$NPJ" ] && case "$NPJ" in /*) ;; *) NPJ="$SP6BINS/config/$NPJ" ;; esac

notify() {
    echo "{\"id\":\"$NOTIFY_ID\",\"state\":\"$1\"}" \
        | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
}

log() {
    echo "[ioc-flash/$LABEL] $*" | tee -a "$LOG_FILE"
}

# One flash at a time. streamdeck-ctrl already swallows presses on a key that
# is running, but not presses of a *different* board's key, and this also
# covers the script being started from somewhere else.
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[ioc-flash/$LABEL] Another flash is already in progress, ignoring" >&2
    exit 0
fi

: > "$LOG_FILE"
notify running

REQUIRED=( "$FLASH_TOOL" "$FIRMWARE" )
[ -n "$NPJ" ] && REQUIRED+=( "$NPJ" )
[ -n "$EXPECT_APP" ] && REQUIRED+=( "$DISPTOOL" )
for f in "${REQUIRED[@]}"; do
    if [ ! -r "$f" ]; then
        log "ERROR: missing $f (is micropanel installed under $MICROPANEL_HOME?)"
        notify failure
        exit 1
    fi
done

# --board must be the first argument to rh850-flash-auto.sh.
ARGS=( --board="$BOARD" )
[ -n "$NPJ" ] && ARGS+=( --npj="$NPJ" )
ARGS+=( --bios-autorun="$FIRMWARE" )

log "Flashing $LABEL with $(basename "$FIRMWARE")"
stdbuf -oL -eL "$FLASH_TOOL" "${ARGS[@]}" >>"$LOG_FILE" 2>&1
STATUS=$?

# The flasher has already verified the written flash; this checks that the new
# application actually boots and identifies itself.
app_running() {
    local deadline=$(( SECONDS + APP_CHECK_TIMEOUT_SEC )) out name
    while [ "$SECONDS" -lt "$deadline" ]; do
        out=$(timeout 10 "$DISPTOOL" --device=ioc --command=iocversion 2>&1 \
              | sed 's/\x1b\[[0-9;]*m//g')
        name=$(printf '%s\n' "$out" | sed -n 's/^App Name *: *//p' | tr -d '[:space:]')
        if [ "$name" = "$EXPECT_APP" ]; then
            log "IOC reports App Name '$name'"
            printf '%s\n' "$out" >>"$LOG_FILE"
            return 0
        fi
        sleep 1
    done
    log "IOC did not report App Name '$EXPECT_APP' within ${APP_CHECK_TIMEOUT_SEC}s (last: '${name:-no answer}')"
    return 1
}

if [ "$STATUS" -eq 0 ] && [ -n "$EXPECT_APP" ] && ! app_running; then
    STATUS=1
fi

if [ "$STATUS" -eq 0 ]; then
    log "Flash completed successfully"
    notify success
else
    log "Flash FAILED (exit $STATUS), see $LOG_FILE"
    notify failure
fi

exit "$STATUS"
