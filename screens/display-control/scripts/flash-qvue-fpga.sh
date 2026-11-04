#!/bin/bash
# Write the 3x QVue's FPGA configuration flash (GOLDEN + UPDATE pair) through
# the QVue's own MCU over I2C, and report the outcome back to the deck.
#
# The QVue has no JTAG path (owner's rule: no JTAG writes on this board). The
# RH850 running QVUE_9090 display_manager owns the FPGA's SPI config flash and
# exposes it on I2C page 0x07; disptool's `fpgaflash` drives that. This is the
# baseline "wire session" from sp6bins firmware/fpga/README.md:
#
#   fpgaflash begin --value2=1                (display off, PROGRAM_B low, 10 MHz SCK)
#   fpgaflash write:<golden>,0,golden         (GOLDEN at 0, about 4 min)
#   fpgaflash write:<update>,0x400000         (UPDATE slot, about 4 min)
#   fpgaflash end                             (PROGRAM_B released, FPGA boots)
#
# then requires `fpgaident` to show FPGA link 0x01 and the expected image byte.
# The MCU must run display_manager (the Qvue-New/IOC-Flash key installs it);
# with the vendor or a superseded FPGA image running, the direct path still
# works, which is the point of the wire session.
#
# A write that fails is retried once. If it still fails, the session is LEFT
# OPEN on purpose (display off, PROGRAM_B low) so the FPGA does not try to
# boot a half-written flash: the key goes red, and pressing it again resumes
# in the open session and rewrites both images.
#
# Usage:
#   flash-qvue-fpga.sh --id=<notification-id> --golden=<file> --update=<file> \
#                      --expect-image=<hex byte, e.g. D8> [--label=<name>]
#
#   --golden / --update  filename under $SP6BINS/firmware/fpga, or an absolute path
#
# The key that launches this is a `task` key: streamdeck-ctrl paints a blinking
# green border while this runs, and the states pushed below leave it solid
# green (success) or solid red (failure).

MICROPANEL_HOME="${MICROPANEL_HOME:-/home/pi/micropanel}"
DISPTOOL="$MICROPANEL_HOME/bin/disptool"
SP6BINS="$MICROPANEL_HOME/share/sp6bins"

SOCK="/run/streamdeck-ctrl/notify.sock"
LOG_FILE="/tmp/qvue-fpga-flash.log"
# Shared with flash-ioc.sh / flash-fpga.sh / flash-touch.sh: an IOC flash
# resets the very MCU this talks through, so only one programming run at a time.
LOCK_FILE="/tmp/target-flash.lock"
# How long the FPGA gets after `end` to configure and answer IDENTIFY.
IDENT_TIMEOUT_SEC=30

NOTIFY_ID=""
GOLDEN=""
UPDATE=""
EXPECT_IMAGE=""
LABEL=""

for arg in "$@"; do
    case "$arg" in
        --id=*)           NOTIFY_ID="${arg#*=}" ;;
        --golden=*)       GOLDEN="${arg#*=}" ;;
        --update=*)       UPDATE="${arg#*=}" ;;
        --expect-image=*) EXPECT_IMAGE="${arg#*=}" ;;
        --label=*)        LABEL="${arg#*=}" ;;
        *) echo "[qvue-fpga] Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

[ -n "$NOTIFY_ID" ]    || { echo "[qvue-fpga] --id is required" >&2; exit 2; }
[ -n "$GOLDEN" ]       || { echo "[qvue-fpga] --golden is required" >&2; exit 2; }
[ -n "$UPDATE" ]       || { echo "[qvue-fpga] --update is required" >&2; exit 2; }
[ -n "$EXPECT_IMAGE" ] || { echo "[qvue-fpga] --expect-image is required" >&2; exit 2; }
[ -n "$LABEL" ]        || LABEL="QVue-FPGA"
EXPECT_IMAGE=$(printf '%s' "${EXPECT_IMAGE#0x}" | tr '[:lower:]' '[:upper:]')

case "$GOLDEN" in /*) ;; *) GOLDEN="$SP6BINS/firmware/fpga/$GOLDEN" ;; esac
case "$UPDATE" in /*) ;; *) UPDATE="$SP6BINS/firmware/fpga/$UPDATE" ;; esac

notify() {
    echo "{\"id\":\"$NOTIFY_ID\",\"state\":\"$1\"}" \
        | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
}

log() {
    echo "[qvue-fpga/$LABEL] $*" | tee -a "$LOG_FILE"
}

fail() {
    log "FAILED: $*"
    log "see $LOG_FILE"
    notify failure
    exit 1
}

strip_ansi() {
    sed 's/\x1b\[[0-9;]*m//g'
}

# disptool, output into the log (colour codes stripped).
dt() {
    stdbuf -oL -eL "$DISPTOOL" --device=ioc "$@" 2>&1 | strip_ansi >>"$LOG_FILE"
    return "${PIPESTATUS[0]}"
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[qvue-fpga/$LABEL] Another flash is already in progress, ignoring" >&2
    exit 0
fi

: > "$LOG_FILE"
notify running

for f in "$DISPTOOL" "$GOLDEN" "$UPDATE"; do
    [ -r "$f" ] || fail "missing $f (is micropanel installed under $MICROPANEL_HOME?)"
done

# The flash is reached through display_manager's page 0x07; nothing else on
# this board serves it (qvue_legacy, the vendor firmware: 0x66 is silent or
# has no page 0x07). Reads of 0x66 are safe on every QVue firmware.
app=$(timeout 15 "$DISPTOOL" --device=ioc --command=iocversion 2>&1 | strip_ansi \
      | sed -n 's/^App Name *: *//p' | tr -d '[:space:]')
[ "$app" = display_manager ] || \
    fail "the QVue MCU runs '${app:-nothing on 0x66}', not display_manager: press Qvue-New/IOC-Flash first"

write_image() {   # <file> <address> [golden]
    local spec="write:$1,$2${3:+,$3}" try
    for try in 1 2; do
        log "Writing $(basename "$1") at $2${3:+ ($3)}, attempt $try (about 4 min)"
        dt --command=fpgaflash --value="$spec" && return 0
        log "write of $(basename "$1") failed (exit $?)"
    done
    return 1
}

START=$SECONDS
log "Opening the wire session (display off, PROGRAM_B low, 10 MHz flash SCK)"
dt --command=fpgaflash --value=begin --value2=1 || fail "fpgaflash begin"

write_image "$GOLDEN" 0 golden || \
    fail "GOLDEN write; the session is left open (display off) so the FPGA does not boot a half-written flash. Press the key again to retry"
write_image "$UPDATE" 0x400000 || \
    fail "UPDATE write; the session is left open (display off) so the FPGA does not boot a half-written flash. Press the key again to retry"

log "Closing the session (PROGRAM_B released, FPGA reconfigures)"
dt --command=fpgaflash --value=end || fail "fpgaflash end"

# FPGA link 0x01 and IDENTIFY's release word ending in 00 <image>, e.g.
#   FPGA link  : 0x01  PPSPI
#   IDENTIFY   : 50 01 17 93 | 11 03 00 D8 | ...
deadline=$(( SECONDS + IDENT_TIMEOUT_SEC ))
while :; do
    ident=$(timeout 15 "$DISPTOOL" --device=ioc --command=fpgaident 2>&1 | strip_ansi)
    link=$(printf '%s\n' "$ident" | sed -n 's/^FPGA link *: *\(0x[0-9A-Fa-f]*\).*/\1/p')
    image=$(printf '%s\n' "$ident" | sed -n 's/^IDENTIFY *: *[0-9A-F ]*| *[0-9A-F][0-9A-F] [0-9A-F][0-9A-F] 00 \([0-9A-F][0-9A-F]\) |.*/\1/p')
    if [ "$link" = 0x01 ] && [ "$image" = "$EXPECT_IMAGE" ]; then
        printf '%s\n' "$ident" >>"$LOG_FILE"
        break
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
        printf '%s\n' "$ident" >>"$LOG_FILE"
        fail "after the flash fpgaident shows link '${link:-?}', image '${image:-?}' (want 0x01, $EXPECT_IMAGE)"
    fi
    sleep 2
done

log "FPGA link 0x01, image 0x$EXPECT_IMAGE running; done in $(( SECONDS - START )) s"
notify success
exit 0
