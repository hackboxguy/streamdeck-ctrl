#!/bin/bash
# Write the 3x QVue's FPGA configuration flash through the QVue's own MCU
# over I2C, and report the outcome back to the deck. Used by
#   Qvue-Legacy/FPGA-Flash  the vendor image back at offset 0, as delivered
#                           (no --update; the UPDATE slot is left as it is,
#                           the vendor image never jumps there)
#
# The QVue has no JTAG path (owner's rule: no JTAG writes on this board). The
# RH850 running QVUE_9090 display_manager owns the FPGA's SPI config flash and
# exposes it on I2C page 0x07; disptool's `fpgaflash` drives that. This is the
# baseline "wire session" from sp6bins firmware/fpga/README.md:
#
#   fpgaflash abort                           (start clean: an open session is resumed in its own mode)
#   fpgaflash begin                           (display off, PROGRAM_B low, 1 MHz SCK: I2C dominates the time)
#   fpgaflash write:<golden>,0,golden         (GOLDEN at 0, about 4 min)
#   fpgaflash write:<update>,0x400000         (UPDATE slot, about 4 min; only with --update)
#   fpgaflash end                             (PROGRAM_B released, FPGA boots)
#
# A begin whose flash ID read fails ("flash id is not 9D 60 18"; FF FF FF =
# the flash does not answer) is closed again at once and reported: power-cycle
# the QVue fully and retry, then hardware. (Qvue-New/FPGA-Flash and OTA-FPGA
# run ota-update.sh fpga: the update flow, GOLDEN only where 0 is not ours.)
#
# then requires `end` to report DONE (the FPGA configured) and `fpgaident` to
# show the expected FPGA link: 0x01 plus the expected IDENTIFY image byte for
# the pixelpipe pair, 0xFF for the vendor image (display_manager cannot talk
# to it; the panel runs at the vendor bitstream's own level). The expected
# image byte is the `version:` of the --update file (else --golden) in the
# installed sp6bins firmware/fpga/manifest.txt, so a new UPDATE release
# (0xD9, ...) needs a new 3xqvue-update.bin + manifest.txt, not a key change. als-dimmer is stopped for the session (it talks to
# the same MCU) and started again afterwards if it was running.
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
#   flash-qvue-fpga.sh --id=<notification-id> --golden=<file> [--update=<file>] \
#                      [--expect-link=0x01|0xFF] [--expect-image=<hex byte, e.g. D8>] \
#                      [--label=<name>]
#
#   --expect-link   default 0x01
#   --expect-image  override for the manifest's version (link 0x01 only)
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
EXPECT_LINK="0x01"
LABEL=""

for arg in "$@"; do
    case "$arg" in
        --id=*)           NOTIFY_ID="${arg#*=}" ;;
        --golden=*)       GOLDEN="${arg#*=}" ;;
        --update=*)       UPDATE="${arg#*=}" ;;
        --expect-image=*) EXPECT_IMAGE="${arg#*=}" ;;
        --expect-link=*)  EXPECT_LINK="${arg#*=}" ;;
        --label=*)        LABEL="${arg#*=}" ;;
        *) echo "[qvue-fpga] Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

[ -n "$NOTIFY_ID" ]    || { echo "[qvue-fpga] --id is required" >&2; exit 2; }
[ -n "$GOLDEN" ]       || { echo "[qvue-fpga] --golden is required" >&2; exit 2; }
[ -n "$LABEL" ]        || LABEL="QVue-FPGA"
EXPECT_LINK=$(printf '%s' "$EXPECT_LINK" | tr '[:upper:]' '[:lower:]')
EXPECT_LINK="0x$(printf '%s' "${EXPECT_LINK#0x}" | tr '[:lower:]' '[:upper:]')"
case "$EXPECT_LINK" in
    0x01|0xFF) ;;
    *) echo "[qvue-fpga] --expect-link must be 0x01 or 0xFF" >&2; exit 2 ;;
esac

case "$GOLDEN" in /*) ;; *) GOLDEN="$SP6BINS/firmware/fpga/$GOLDEN" ;; esac
[ -n "$UPDATE" ] && case "$UPDATE" in /*) ;; *) UPDATE="$SP6BINS/firmware/fpga/$UPDATE" ;; esac
MANIFEST="$SP6BINS/firmware/fpga/manifest.txt"

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
# Wait up to 3 s: the deck's pollers test this lock with `flock -n <lock> true`,
# which holds it for a moment; a flash runs for minutes, so a real one still refuses.
if ! flock -w 3 9; then
    echo "[qvue-fpga/$LABEL] Another flash is already in progress, ignoring" >&2
    exit 0
fi

: > "$LOG_FILE"
notify running

for f in "$DISPTOOL" "$GOLDEN" ${UPDATE:+"$UPDATE"}; do
    [ -r "$f" ] || fail "missing $f (is micropanel installed under $MICROPANEL_HOME?)"
done

# The image the FPGA must identify as afterwards: the version sp6bins ships
# for the image that boots (the UPDATE slot when one is written). Never a
# guess: no version in the manifest is a failure before anything is touched.
if [ "$EXPECT_LINK" = 0x01 ] && [ -z "$EXPECT_IMAGE" ]; then
    boot_file=$(basename "${UPDATE:-$GOLDEN}")
    [ -r "$MANIFEST" ] || fail "missing $MANIFEST, cannot tell which image $boot_file is"
    EXPECT_IMAGE=$(awk -v f="$boot_file" '
        /^file:/ {cur=$2} cur==f && /^version:/ {print $2; exit}' "$MANIFEST")
    [ -n "$EXPECT_IMAGE" ] || fail "no version: for $boot_file in $MANIFEST"
    log "Expecting image $EXPECT_IMAGE ($boot_file, from manifest.txt)"
fi
EXPECT_IMAGE=$(printf '%s' "$EXPECT_IMAGE" | tr '[:upper:]' '[:lower:]')
EXPECT_IMAGE=$(printf '%s' "${EXPECT_IMAGE#0x}" | tr '[:lower:]' '[:upper:]')
case "$EXPECT_LINK:$EXPECT_IMAGE" in
    0xFF:*|0x01:[0-9A-F][0-9A-F]) ;;
    *) fail "expected image '$EXPECT_IMAGE' is not one hex byte" ;;
esac

# als-dimmer drives the QVue's brightness through the same MCU; keep it off
# the bus for the session and put it back the way it was on every exit.
ALS_WAS_ACTIVE=0
if systemctl is-active --quiet als-dimmer 2>/dev/null; then
    ALS_WAS_ACTIVE=1
    log "Stopping als-dimmer for the session"
    sudo -n systemctl stop als-dimmer || log "could not stop als-dimmer (continuing)"
fi
restore_als() {
    if [ "$ALS_WAS_ACTIVE" -eq 1 ]; then
        log "Starting als-dimmer again"
        sudo -n systemctl start als-dimmer || log "could not start als-dimmer"
    fi
    # The board's firmware may have changed: refresh the OTA keys once this
    # script has released the flash lock (ota-check.sh --wait waits for it).
    # 9>&-: not the flash lock's fd, or the check would hold the very lock it waits for
    setsid "$(dirname "$0")/ota-check.sh" firmware fpga --wait </dev/null >/dev/null 2>&1 9>&- &
}
trap restore_als EXIT

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
log "Closing any session left open"
dt --command=fpgaflash --value=abort || fail "fpgaflash abort (an open session could not be closed)"
log "Opening the wire session (display off, PROGRAM_B low, 1 MHz flash SCK)"
begin_out=$(stdbuf -oL -eL "$DISPTOOL" --device=ioc --command=fpgaflash --value=begin 2>&1 | strip_ansi)
begin_rc=${PIPESTATUS[0]}
printf '%s\n' "$begin_out" >>"$LOG_FILE"
if [ "$begin_rc" -ne 0 ]; then
    if id_line=$(printf '%s\n' "$begin_out" | grep -m1 'flash id is not 9D 60 18'); then
        dt --command=fpgaflash --value=abort
        id_read=$(printf '%s\n' "$id_line" | sed -n 's/.*(read 0x\(..\) 0x\(..\) 0x\(..\)).*/\1 \2 \3/p')
        fail "the FPGA config flash did not answer (ID ${id_read:-not read}, expected 9D 60 18). Nothing was written. Power-cycle the QVue fully and retry; if it persists: hardware / JTAG"
    fi
    dt --command=fpgaflash --value=abort
    fail "fpgaflash begin (exit $begin_rc)"
fi

write_image "$GOLDEN" 0 golden || \
    fail "GOLDEN write; the session is left open (display off) so the FPGA does not boot a half-written flash. Press the key again to retry"
if [ -n "$UPDATE" ]; then
    write_image "$UPDATE" 0x400000 || \
        fail "UPDATE write; the session is left open (display off) so the FPGA does not boot a half-written flash. Press the key again to retry"
fi

log "Closing the session (PROGRAM_B released, FPGA reconfigures)"
end_out=$(stdbuf -oL -eL "$DISPTOOL" --device=ioc --command=fpgaflash --value=end 2>&1 | strip_ansi)
end_rc=${PIPESTATUS[0]}
printf '%s\n' "$end_out" >>"$LOG_FILE"
[ "$end_rc" -eq 0 ] || fail "fpgaflash end (exit $end_rc)"
# Link 0xFF alone cannot tell the vendor image from an FPGA that did not
# configure at all; DONE can. The MCU reports FU_DONE_MS 0xFFFF on a timeout.
done_ms=$(printf '%s\n' "$end_out" | sed -n 's/.*DONE after \([0-9][0-9]*\) ms.*/\1/p' | head -1)
if [ -z "$done_ms" ] || [ "$done_ms" -ge 65535 ]; then
    fail "the FPGA did not report DONE after fpgaflash end (${done_ms:-no DONE line}): it did not configure"
fi
log "FPGA configured (DONE after $done_ms ms)"

# Pixelpipe pair: FPGA link 0x01 and IDENTIFY's release word ending in
# 00 <image>, e.g.
#   FPGA link  : 0x01  PPSPI
#   IDENTIFY   : 50 01 17 93 | 11 03 00 D8 | ...
# Vendor image: FPGA link 0xFF, or 0x02 from display_manager v01.10 on (its
# vendor-frame shim); no PPSPI either way.
deadline=$(( SECONDS + IDENT_TIMEOUT_SEC ))
while :; do
    ident=$(timeout 15 "$DISPTOOL" --device=ioc --command=fpgaident 2>&1 | strip_ansi)
    link=$(printf '%s\n' "$ident" | sed -n 's/^FPGA link *: *\(0x[0-9A-Fa-f]*\).*/\1/p')
    image=$(printf '%s\n' "$ident" | sed -n 's/^IDENTIFY *: *[0-9A-F ]*| *[0-9A-F][0-9A-F] [0-9A-F][0-9A-F] 00 \([0-9A-F][0-9A-F]\) |.*/\1/p')
    link=0x$(printf '%s' "${link#0x}" | tr '[:lower:]' '[:upper:]')
    # The vendor image: 0xFF on display_manager before its vendor-frame shim,
    # 0x02 ("legacy vendor frame (shim)") from v01.10 on.
    vendor_link=0
    [ "$EXPECT_LINK" = 0xFF ] && { [ "$link" = 0xFF ] || [ "$link" = 0x02 ]; } && vendor_link=1
    if [ "$vendor_link" = 1 ] || { [ "$link" = "$EXPECT_LINK" ] && [ "$EXPECT_LINK" = 0x01 ] && [ "$image" = "$EXPECT_IMAGE" ]; }; then
        printf '%s\n' "$ident" >>"$LOG_FILE"
        break
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
        printf '%s\n' "$ident" >>"$LOG_FILE"
        fail "after the flash fpgaident shows link '${link:-?}', image '${image:-?}' (want $([ "$EXPECT_LINK" = 0xFF ] && echo "0xFF or 0x02, the vendor image" || echo "$EXPECT_LINK, $EXPECT_IMAGE"))"
    fi
    sleep 2
done

if [ "$EXPECT_LINK" = 0xFF ]; then
    log "FPGA link $link: the vendor image is running; done in $(( SECONDS - START )) s"
else
    log "FPGA link 0x01, image 0x$EXPECT_IMAGE running; done in $(( SECONDS - START )) s"
fi
notify success
exit 0
