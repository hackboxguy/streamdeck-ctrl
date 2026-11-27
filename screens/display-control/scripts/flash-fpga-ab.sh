#!/bin/bash
# JTAG-install a Spartan-7 (XC7S50 / XA7S50) display board's A/B pair: GOLDEN at
# flash address 0, UPDATE in the slot at 0x400000 -- also the first time, on a
# board that still carries the vendor image -- and report it to the deck.
#
#   flash-fpga-ab.sh --id=<notification id> --golden=<file> --update=<file> [--label=<name>]
#
# The files are names in $FPGA_DIR (sp6bins firmware/fpga); both must be in its
# manifest.txt with the same sha256. The flow (sp6bins docs/fpga-ab-update-procedure.md,
# tmp-docs/first-time-vendor-firmware-upgrade-process.md), all over JTAG through
# a flash bridge loaded into the FPGA, never resetting the FPGA between steps.
#
# Two JTAG cables ($FPGA_JTAG_TRANSPORT = auto | usb-blaster | xpc2; auto takes
# the USB-Blaster when it is attached, else the Platform Cable):
#   usb-blaster  09fb:6001, openFPGALoader + spiOverJtag_xc7s50 (--skip-reset)
#   xpc2         Xilinx Platform Cable USB II / Waveshare clone 03fd:0013,
#                xc3sprog + bscan_spi xc7s50csga324-1. Its FX2 firmware
#                (xusb_xp2.hex) is loaded with fxload when the cable does not
#                answer. xc3sprog leaves the bridge loaded after every call, like
#                --skip-reset; it cannot reset a 7-series part, so on this cable
#                the IOC display power cycle is the only reconfiguration.
#
#   1. check the images (fpga-ab-image.py check): headers, IDCODE, sizes, sha256
#   2. probe: the cable, IDCODE 0x0362f093, flash JEDEC 0x9d6018
#   3. read the combined range back and classify it (never guess):
#        GOLDEN at 0 and UPDATE in the slot  -> nothing to write
#        GOLDEN at 0, the slot differs       -> the slot only (GOLDEN is never rewritten)
#        anything else at 0 (vendor, blank, a cut write)
#                                            -> GOLDEN + UPDATE, without asking
#      Before that write the whole 16 MiB flash is backed up (to $BACKUP_DIR; its
#      first range must equal the step-3 read), then GOLDEN + UPDATE are written
#      as ONE image in ONE JTAG session (write + verify, no reset): the old
#      image never runs between the two writes.
#   4. read the written range back and compare it byte for byte
#   5. one deliberate reconfiguration: display power off/on through the display
#      IOC (cycles the FPGA rails and re-initialises the display side);
#      a JTAG reset only if the IOC does not answer (USB-Blaster only)
#   6. success only when the FPGA runs the UPDATE from the slot: activbitstream
#      OTA, the version byte the manifest gives, update-fpga.sh --verify ok
#
# A power loss or a failure in any step is safe to rerun: the JTAG path needs no
# configured FPGA, and the flow verifies before it writes.
#
# One press does everything: there is no question in the middle. A second press
# while a run is going finds the lock held and is ignored.
#
# Locks: /tmp/target-flash.lock (every flash script and the deck's pollers) and
# System Manager's /tmp/system-update.lock. als-dimmer is stopped for the run.
# Log: /tmp/fpga-flash.log.

set -u
cd "$(dirname "$0")" || exit 1
. ./ota-lib.sh

OFL="${OFL:-$MICROPANEL_HOME/fpga/bin/openFPGALoader}"
BRIDGE="${OFL_BRIDGE:-$MICROPANEL_HOME/fpga/share/openFPGALoader/spiOverJtag_xc7s50.bit.gz}"
XC3SPROG="${XC3SPROG:-$MICROPANEL_HOME/fpga/bin/xc3sprog}"
BSCAN="${XC3SPROG_BSCAN:-$MICROPANEL_HOME/fpga/share/xc3sprog/bscan_spi/xc7s50csga324-1.bit}"
XPC_FIRMWARE="${XPC_FIRMWARE:-$MICROPANEL_HOME/fpga/bin/xusb_xp2.hex}"
FXLOAD="${FXLOAD:-fxload}"
TRANSPORT_WANT=${FPGA_JTAG_TRANSPORT:-auto}
UPDATE_FPGA="${UPDATE_FPGA:-$BIN/update-fpga.sh}"
IMAGE_TOOL="$PWD/fpga-ab-image.py"
BACKUP_DIR="${FPGA_BACKUP_DIR:-/data/fpga-backups}"
WORK="${FPGA_AB_WORK:-$OTA_TMP/fpga-ab}"
LOG_FILE="$OTA_TMP/fpga-flash.log"
POWER_OFF_SEC=${FPGA_AB_POWER_OFF_SEC:-3}
BOOT_WAIT_SEC=${FPGA_AB_BOOT_WAIT_SEC:-30}
# Tests run unprivileged against a fake openFPGALoader / xc3sprog
OFL_SUDO=${FPGA_AB_OFL_SUDO:-1}

SLOT=0x400000
FLASH_SIZE=16777216
IDCODE=0x362f093
JEDEC=0x9d6018
BLASTER=09fb:6001
XPC=03fd:0013

ID="" LABEL="" GOLDEN="" UPDATE=""
for a in "$@"; do
    case "$a" in
        --id=?*)     ID=${a#*=} ;;
        --label=?*)  LABEL=${a#*=} ;;
        --golden=?*) GOLDEN=${a#*=} ;;
        --update=?*) UPDATE=${a#*=} ;;
        *) echo "$0: unknown argument $a" >&2; exit 2 ;;
    esac
done
[ -n "$ID" ] && [ -n "$GOLDEN" ] && [ -n "$UPDATE" ] || {
    echo "usage: $0 --id=<id> --golden=<file> --update=<file> [--label=<name>]" >&2; exit 2; }
LABEL=${LABEL:-$GOLDEN}

log() { echo "[fpga-ab/$LABEL] $*" | tee -a "$LOG_FILE"; }

BRIDGE_LOADED=0   # the FPGA holds the bridge, not a design: reconfigure before leaving
WRITING=0         # a write began: leave the FPGA alone, a rerun completes it
fail() {
    log "FAILED: $*"
    if [ "$BRIDGE_LOADED" = 1 ] && [ "$WRITING" = 0 ]; then
        log "nothing was written; giving the FPGA its image back"
        # The vendor image has no 0x1E interface: no answer is expected there.
        reconfigure nowait || log "could not reconfigure: power-cycle the display"
    fi
    push "$ID" failure
    exit 1
}

# ---- locks -----------------------------------------------------------------------
exec 9>"$FLASH_LOCK" || { echo "cannot open $FLASH_LOCK" >&2; exit 1; }
# Wait up to 3 s: the deck's pollers test this lock with `flock -n <lock> true`,
# which holds it for a moment; a flash runs for minutes, so a real one still refuses.
if ! flock -w 3 9; then
    echo "[fpga-ab/$LABEL] another flash is in progress, ignoring" >&2
    exit 0
fi
if system_lock_held; then
    log "System Manager is updating"
    push "$ID" failure
    exit 1
fi
echo $$ > "$SYSTEM_LOCK" 2>/dev/null || { push "$ID" failure; exit 1; }
ALS_WAS_ACTIVE=0
TICKER=""
cleanup() {
    [ -n "$TICKER" ] && kill "$TICKER" 2>/dev/null
    rm -rf "$WORK"
    [ "$(cat "$SYSTEM_LOCK" 2>/dev/null)" = "$$" ] && rm -f "$SYSTEM_LOCK"
    if [ "$ALS_WAS_ACTIVE" -eq 1 ]; then
        priv systemctl start als-dimmer 2>/dev/null && log "als-dimmer started again"
    fi
}
trap cleanup EXIT

: > "$LOG_FILE"
push "$ID" running 0
log "start ($(date '+%F %T')): $GOLDEN at 0x0, $UPDATE at $SLOT"

# progress <from> <to> <seconds>: a linear estimate for the next step
progress() {
    [ -n "$TICKER" ] && kill "$TICKER" 2>/dev/null
    local from=$1 to=$2 secs=$3
    push_progress "$ID" "$from"
    ( t0=$SECONDS
      while sleep 1; do
          p=$(( from + (SECONDS - t0) * (to - from) / secs )); [ "$p" -gt "$to" ] && p=$to
          push_progress "$ID" "$p"
      done ) 9>&- &
    TICKER=$!
}

priv() {
    if [ "$OFL_SUDO" = 1 ]; then as_root "$@"; else "$@"; fi
}
ofl() { priv "$OFL" -c usb-blaster "$@"; }
xc3() { priv "$XC3SPROG" -c xpc2 "$@"; }
usb_present() { "${LSUSB:-lsusb}" -d "$1" 2>/dev/null | grep -q .; }

XC3_BANNER='^(XC3SPROG|Free software|Feedback on|Check Sourceforge|[[:space:]]*http)'

# jtag_step <what> <args...>: one JTAG call through the flash bridge; its output
# (without the progress bars) goes to the log. xc3sprog does not always exit
# non-zero on a failure, so its output is checked as well -- without its banner,
# which always says "Feedback on success/failure/enhancement requests".
jtag_step() {
    local what=$1 rc; shift
    BRIDGE_LOADED=1
    if [ "$TRANSPORT" = xpc2 ]; then
        xc3 -I"$BSCAN" "$@" > "$WORK/jtag.out" 2>&1
    else
        ofl -B "$BRIDGE" "$@" > "$WORK/jtag.out" 2>&1
    fi
    rc=$?
    tr '\r' '\n' < "$WORK/jtag.out" | grep -v -E "%|^[[:space:]]*\$|$XC3_BANNER" >>"$LOG_FILE"
    if [ "$rc" -eq 0 ] && [ "$TRANSPORT" = xpc2 ] \
        && grep -vE "$XC3_BANNER" "$WORK/jtag.out" | grep -qiE 'fail|error|mismatch|usage:'; then
        rc=1
    fi
    if [ "$rc" -ne 0 ]; then
        log "$what: ${TRANSPORT_TOOL} exit $rc"
        return 1
    fi
    log "$what: ok"
}

# The bridge operations, one per transport. Every one leaves the bridge loaded.
flash_probe() {
    if [ "$TRANSPORT" = xpc2 ]; then jtag_step "flash probe"
    else jtag_step "flash probe" --detect -f; fi
}
# flash_read <what> <file> <bytes>: flash 0x0 .. bytes-1 into file
flash_read() {
    if [ "$TRANSPORT" = xpc2 ]; then jtag_step "$1" "$2:R:0:BIN:$3"
    else jtag_step "$1" --skip-reset --dump-flash "$2" --file-size "$3"; fi
}
# flash_write <what> <file> <offset>: sector erase, write, verify
flash_write() {
    if [ "$TRANSPORT" = xpc2 ]; then
        jtag_step "$1" "$2:W:$(( $3 )):BIN" || return 1
        grep -q "Verify: Success" "$WORK/jtag.out" || { log "$1: xc3sprog did not report a verify"; return 1; }
    elif [ "$(( $3 ))" -eq 0 ]; then jtag_step "$1" --skip-reset --verify -f "$2" --file-type bin
    else jtag_step "$1" --skip-reset --verify -o "$3" -f "$2" --file-type bin; fi
}
# jtag_reset: reconfigure the FPGA from flash over JTAG (JPROGRAM)
jtag_reset() {
    if [ "$TRANSPORT" = xpc2 ]; then
        log "xc3sprog cannot reset a 7-series FPGA over the Platform Cable"
        return 1
    fi
    ofl --reset >>"$LOG_FILE" 2>&1
}

# xpc_ready: 0 once the Platform Cable answers (DET holds its chain scan). A
# cable that comes up without firmware (its FX2 boots empty) gets xusb_xp2.hex;
# both fxload syntaxes are tried (classic -t/-I/-D and the newer load_ram).
xpc_ready() {
    local dev
    DET=$(xc3 -j 2>&1)
    printf '%s\n' "$DET" | grep -qi "idcode" && return 0
    [ -r "$XPC_FIRMWARE" ] || { log "missing $XPC_FIRMWARE"; return 1; }
    dev=$("${LSUSB:-lsusb}" -d "$XPC" 2>/dev/null \
        | sed -nE 's#^Bus ([0-9]+) Device ([0-9]+).*#/dev/bus/usb/\1/\2#p' | head -1)
    log "loading the Platform Cable firmware ($XPC_FIRMWARE, $dev)"
    priv "$FXLOAD" -t fx2lp -I "$XPC_FIRMWARE" -D "$dev" >>"$LOG_FILE" 2>&1 \
        || priv "$FXLOAD" load_ram --ihex-path "$XPC_FIRMWARE" --device "$XPC" -t FX2LP >>"$LOG_FILE" 2>&1 \
        || { log "fxload failed"; return 1; }
    for _ in $(seq 1 10); do
        sleep 1
        DET=$(xc3 -j 2>&1)
        printf '%s\n' "$DET" | grep -qi "idcode" && return 0
    done
    log "the Platform Cable does not answer after the firmware load"
    return 1
}

# The FPGA's version register (4 bytes, "10 18 00 88") and running slot
fpga_version() {
    timeout 10 "$DISPTOOL" --device=fpganew --command=version 2>/dev/null | strip_ansi \
        | sed -n 's/^Raw Bytes *: *//p' | head -1
}
fpga_slot() {
    timeout 10 "$DISPTOOL" --device=fpganew --command=activbitstream 2>/dev/null | strip_ansi \
        | grep -oE 'OTA|GOLDEN' | head -1
}

# wait_answer: 0 (and V set) once the FPGA's version register answers
wait_answer() {
    local t0=$SECONDS
    while [ $(( SECONDS - t0 )) -lt "$BOOT_WAIT_SEC" ]; do
        sleep 1
        V=$(fpga_version)
        if [ -n "$V" ]; then
            log "reconfigured ($RECONF_HOW): the FPGA answers after $(( SECONDS - t0 )) s, version $V"
            return 0
        fi
    done
    log "reconfigured ($RECONF_HOW): no answer from the FPGA within $BOOT_WAIT_SEC s"
    return 1
}

# One deliberate reconfiguration; 0 once the FPGA answers again ("nowait": 0
# once the power cycle or reset was done). Through the display IOC's power
# switch first; an openFPGALoader reset where the IOC does not answer, or
# where its power cycle did not restart the FPGA (a board whose rails it
# does not switch); the Platform Cable has no JTAG reset (see the top).
reconfigure() {
    RECONF_HOW=ioc
    if timeout 10 "$DISPTOOL" --device=ioc --command=disppower --value=off >>"$LOG_FILE" 2>&1; then
        sleep "$POWER_OFF_SEC"
        timeout 10 "$DISPTOOL" --device=ioc --command=disppower --value=on >>"$LOG_FILE" 2>&1 \
            || log "display power on did not answer"
        BRIDGE_LOADED=0
        if [ "${1:-}" = nowait ]; then log "reconfigured (ioc)"; return 0; fi
        wait_answer && return 0
        log "the display power cycle did not restart the FPGA; reconfiguring over JTAG instead"
    else
        log "the display IOC did not switch the display power; reconfiguring over JTAG instead"
    fi
    RECONF_HOW=jtag
    jtag_reset || return 1
    BRIDGE_LOADED=0
    if [ "${1:-}" = nowait ]; then log "reconfigured (jtag)"; return 0; fi
    wait_answer
}

# ---- 1. images --------------------------------------------------------------------
G="$FPGA_DIR/$GOLDEN"; U="$FPGA_DIR/$UPDATE"
for f in "$G" "$U" "$FPGA_MANIFEST"; do [ -r "$f" ] || fail "missing $f"; done
VERS=$(python3 -I "$IMAGE_TOOL" check "$G" "$U" "$FPGA_MANIFEST" 2>>"$LOG_FILE") \
    || fail "the images did not pass the checks (see $LOG_FILE); nothing was written"
WANT_UPDATE=$(result_field "$VERS" update_version)
WANT_GOLDEN=$(result_field "$VERS" golden_version)
log "images ok: GOLDEN $WANT_GOLDEN, UPDATE $WANT_UPDATE"
rm -rf "$WORK"; mkdir -p "$WORK" || fail "cannot create $WORK"
COMBINED="$WORK/combined.bin"
python3 -I "$IMAGE_TOOL" combine "$G" "$U" "$COMBINED" || fail "cannot build the combined image"
SPAN=$(stat -c %s "$COMBINED")

# ---- 2. probe ---------------------------------------------------------------------
case "$TRANSPORT_WANT" in
    usb-blaster) TRANSPORT=usb-blaster ;;
    xpc2)        TRANSPORT=xpc2 ;;
    auto)        if usb_present "$BLASTER"; then TRANSPORT=usb-blaster
                 elif usb_present "$XPC"; then TRANSPORT=xpc2
                 else fail "no JTAG cable attached (USB-Blaster $BLASTER or Platform Cable USB II $XPC)"; fi ;;
    *)           fail "unknown FPGA_JTAG_TRANSPORT=$TRANSPORT_WANT (auto, usb-blaster or xpc2)" ;;
esac
if [ "$TRANSPORT" = xpc2 ]; then
    TRANSPORT_TOOL=xc3sprog
    # Measured on the Pi 4 (2026-11-19): read 69 kB/s, sector erase + write + verify 20 kB/s
    RD_BPS=69000 WR_BPS=20000
    [ -x "$XC3SPROG" ] || fail "missing $XC3SPROG"
    [ -r "$BSCAN" ] || fail "missing $BSCAN"
    usb_present "$XPC" || fail "no Platform Cable USB II ($XPC) attached"
else
    TRANSPORT_TOOL=openFPGALoader
    RD_BPS=46000 WR_BPS=15000
    [ -x "$OFL" ] || fail "missing $OFL"
    [ -r "$BRIDGE" ] || fail "missing $BRIDGE"
    usb_present "$BLASTER" || fail "no USB-Blaster ($BLASTER) attached"
fi
log "JTAG cable: $TRANSPORT ($TRANSPORT_TOOL)"
if systemctl is-active --quiet als-dimmer 2>/dev/null; then
    priv systemctl stop als-dimmer && ALS_WAS_ACTIVE=1 && log "als-dimmer stopped for the run"
fi
if [ "$TRANSPORT" = xpc2 ]; then
    xpc_ready || fail "the Platform Cable USB II does not answer; nothing was written"
else
    DET=$(ofl --detect 2>&1)
fi
# openFPGALoader prints "idcode 0x362f093", xc3sprog "IDCODE: 0x0362f093"
printf '%s\n' "$DET" | grep -qiE "idcode:? *0x0?${IDCODE#0x}" \
    || fail "no XC7S50 on the JTAG chain (expected IDCODE $IDCODE): $(printf '%s' "$DET" | grep -i idcode | head -1)"
progress 1 4 10
flash_probe
# openFPGALoader prints "JEDEC ID: 0x9d6018", xc3sprog "JEDEC: 9d 60 0x18"
grep -qE "JEDEC ID: $JEDEC|JEDEC: 9d 60 0x18" "$LOG_FILE" \
    || fail "the config flash is not the IS25LP128 ($JEDEC); nothing was written. Power-cycle the display fully and run again"

# ---- 3. what the flash holds ---------------------------------------------------------
progress 4 12 $(( SPAN / RD_BPS + 5 ))
flash_read "read 0x0+$SPAN" "$WORK/before.bin" "$SPAN" \
    || fail "reading the flash failed"
STATE=$(python3 -I "$IMAGE_TOOL" classify "$WORK/before.bin" "$G" "$U" 2>>"$LOG_FILE") \
    || fail "cannot classify the readback"
A0=$(result_field "$STATE" addr0); SL=$(result_field "$STATE" slot)
log "flash holds: address 0 $A0, slot $SL"

OUTCOME=""
if [ "$A0" = golden ] && [ "$SL" = match ]; then
    OUTCOME="already installed"
    log "GOLDEN and UPDATE are already in place: nothing to write"
elif [ "$A0" = golden ]; then
    OUTCOME="updated"
    WRITING=1
    progress 12 80 $(( $(stat -c %s "$U") / WR_BPS + 20 ))
    flash_write "write $UPDATE at $SLOT (verify)" "$U" "$SLOT" || fail "writing the slot failed; run the key again (GOLDEN at 0 is untouched)"
else
    case "$A0" in
        blank) what="an empty address 0" ;;
        *)     what="an image at address 0 that is not our GOLDEN (the vendor image, or a cut write)" ;;
    esac
    log "the board has $what: installing GOLDEN at 0 and the UPDATE in the slot"
    log "backup, then the write; keep the display powered. A power loss while writing leaves the FPGA dark until this key is run again (JTAG needs no working image)"

    mkdir -p "$BACKUP_DIR" 2>/dev/null || priv mkdir -p "$BACKUP_DIR" \
        || fail "cannot create $BACKUP_DIR; nothing was written"
    priv chown "$(id -un):$(id -gn)" "$BACKUP_DIR" 2>/dev/null
    BK="$BACKUP_DIR/$(printf '%s' "$LABEL" | tr -c 'A-Za-z0-9._-' '_')-flash-$(date +%Y%m%d-%H%M%S).bin"
    progress 10 40 $(( FLASH_SIZE / RD_BPS + 5 ))
    flash_read "backup of the whole flash" "$BK" "$FLASH_SIZE" \
        || fail "the backup failed; nothing was written"
    priv chown "$(id -un):$(id -gn)" "$BK" 2>/dev/null
    [ "$(stat -c %s "$BK" 2>/dev/null)" = "$FLASH_SIZE" ] || fail "the backup is incomplete; nothing was written"
    # Two independent reads of the range that held the image must agree.
    cmp -s -n "$SPAN" "$BK" "$WORK/before.bin" \
        || fail "the backup and the first read differ (an unreliable read); nothing was written"
    sha256sum "$BK" > "$BK.sha256"
    log "backup: $BK ($(cut -c1-16 "$BK.sha256")...)"

    OUTCOME="migrated"
    WRITING=1
    progress 40 80 $(( SPAN * 10 / (WR_BPS * 14) + 20 ))
    flash_write "write GOLDEN + UPDATE in one session (verify)" "$COMBINED" 0 \
        || fail "the write failed; run the key again (it starts over with the check). Backup: $BK"
fi

# ---- 4. independent readback -----------------------------------------------------------
if [ "$OUTCOME" != "already installed" ]; then
    progress 80 92 $(( SPAN / RD_BPS + 5 ))
    flash_read "readback 0x0+$SPAN" "$WORK/after.bin" "$SPAN" \
        || fail "the readback failed; run the key again"
    cmp -s "$WORK/after.bin" "$COMBINED" || fail "the readback differs from the image; run the key again"
    log "readback: identical to the image"
fi
WRITING=0

# ---- 5. one deliberate reconfiguration ---------------------------------------------------
progress 92 98 15
reconfigure || fail "the FPGA does not answer after the reconfiguration: power-cycle the display; the flash holds GOLDEN + UPDATE"

# ---- 6. judge by what runs -----------------------------------------------------------------
[ -n "$TICKER" ] && kill "$TICKER" 2>/dev/null; TICKER=""
SLOTRUN=$(fpga_slot)
VBYTE=$(printf '%s' "${V:-}" | awk '{print $4}' | sed 's/^0[xX]//' | tr a-f A-F)
WANT=$(printf '%s' "$WANT_UPDATE" | sed 's/^0[xX]//' | tr a-f A-F)
log "running: version ${V:-?}, slot ${SLOTRUN:-?} (expected UPDATE $WANT_UPDATE from OTA)"
[ "$SLOTRUN" = OTA ] && [ "$VBYTE" = "$WANT" ] \
    || fail "the FPGA does not run the UPDATE from the slot (version ${V:-?}, slot ${SLOTRUN:-?}). Power-cycle the display fully; if it stays, see $LOG_FILE"
if [ -x "$UPDATE_FPGA" ]; then
    R=$(priv "$UPDATE_FPGA" --verify --image-dir "$FPGA_DIR" 2>&1 | grep '^RESULT' | tail -1)
    log "update-fpga.sh --verify: ${R:-no RESULT}"
    printf '%s' "$R" | grep -q 'status=ok' || fail "update-fpga.sh --verify did not confirm the slot"
fi

log "SUCCESS: $OUTCOME; running UPDATE $WANT_UPDATE from the slot (reconfigured via $RECONF_HOW)"
push "$ID" success
exit 0
