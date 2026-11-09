#!/bin/bash
# Run one OTA update for the page-6 OTA keys and report it to the deck:
# a blinking green border with a progress bar while it runs, then solid green
# (success) or red (failure). The key only lets this start when it is yellow
# ("available") or red (a retry), after a 1.5 s hold.
#
#   ota-update.sh ioc|983|system
#   ota-update.sh fpga [--force] [--id=<notification id>]
#
#   ioc     the display IOC: on a QVue running display_manager
#           update-iocs.sh --qvue A --qvue-b B --warm (no reset, no power
#           cycle); elsewhere --ots A --ots-b B --keep-stream (power cycle after)
#   983     the 983HH serializer board: update-iocs.sh --983 A --983-b B
#           (power cycle after: touch and the 983's setup come back with it)
#   fpga    the QVue FPGA, the same flow as the flasher VM's Update FPGA:
#           - a pixelpipe image with the OTA engine answers (link 0x01, GOLDEN
#             included): the UPDATE slot by the engine, display on
#             (write:3xqvue-update.bin,0x400000,engine)
#           - anything else (the vendor image as delivered, a cut write, no
#             answer): the direct path (abort, begin, display off). Flash
#             address 0 is checked first: our GOLDEN there -> the UPDATE slot
#             only; the vendor image or something unknown -> the key turns
#             amber and asks (hold it again within 60 s = yes): GOLDEN at 0,
#             then the UPDATE slot, in one session. No answer: nothing written.
#           Then DONE, link 0x01, not GOLDEN, the manifest's image byte.
#           --force: rewrite the UPDATE slot although it is current
#           (Qvue-New/FPGA-Flash); never rewrites a GOLDEN that verifies.
#           --id: the key to report to (default ota.fpga)
#   system  the .mpupdate on the USB stick: ab-update install usb (the engine
#           verifies, writes the inactive slot and reboots by itself)
#
# The board firmware images come from the same --check System Manager runs
# (its image= column: the pair whose board code the board runs). Nothing is
# updated that the check does not call outdated, so a rolled-back image
# (update-iocs exit 5) is never installed again from here.
#
# The FPGA question: while it waits, this run leaves $CONFIRM_WAIT ("<pid>
# <id>"); a press of the same key runs this script again, which finds it,
# leaves $CONFIRM_YES and exits without touching anything else.
#
# Locks: /tmp/target-flash.lock (every flash script and the deck's pollers)
# and /tmp/system-update.lock (System Manager and its badge; this pid inside).
# update-iocs.sh stops als-dimmer itself; the FPGA path stops it here.
# Log: /tmp/ota-update.log.

set -u
cd "$(dirname "$0")" || exit 1
. ./ota-lib.sh

TARGET="${1:-}"
case "$TARGET" in
    ioc) ID=$ID_IOC ;; 983) ID=$ID_983 ;; fpga) ID=$ID_FPGA ;; system) ID=$ID_SYSTEM ;;
    *) echo "usage: $0 ioc|983|fpga|system" >&2; exit 2 ;;
esac
shift
FORCE=${OTA_FORCE:-0}
for a in "$@"; do
    case "$TARGET:$a" in
        fpga:--force) FORCE=1 ;;
        fpga:--id=?*) ID=${a#--id=} ;;
        *) echo "$0 $TARGET: unknown argument $a" >&2; exit 2 ;;
    esac
done

# A press that answers the FPGA question of the run already going: say yes
# and leave everything else to that run (it holds the locks).
if [ "$TARGET" = fpga ] && [ -e "$CONFIRM_WAIT" ]; then
    read -r wpid wid < "$CONFIRM_WAIT" 2>/dev/null
    if [ "${wid:-}" = "$ID" ] && [ -n "${wpid:-}" ] && kill -0 "$wpid" 2>/dev/null; then
        echo yes > "$CONFIRM_YES"
        exit 0
    fi
fi

log() { echo "[ota/$TARGET] $*" | tee -a "$OTA_LOG"; }

fail() {
    log "FAILED: $*"
    push "$ID" failure
    exit 1
}

# ---- locks -------------------------------------------------------------------
exec 9>"$FLASH_LOCK" || fail "cannot open $FLASH_LOCK"
if ! flock -n 9; then
    log "another flash is in progress"
    push "$ID" failure
    exit 1
fi
if system_lock_held; then
    log "System Manager is updating"
    push "$ID" failure
    exit 1
fi
echo $$ > "$SYSTEM_LOCK" 2>/dev/null || fail "cannot write $SYSTEM_LOCK"
ALS_WAS_ACTIVE=0
TICKER=""
cleanup() {
    [ -n "$TICKER" ] && kill "$TICKER" 2>/dev/null
    if [ "$TARGET" = fpga ]; then
        # Interrupted before any write (e.g. while asking): give the FPGA back.
        # After a write began a failure keeps the session open on purpose.
        [ "${SESSION_OPEN:-0}" = 1 ] && [ "${WRITING:-0}" = 0 ] && fpga_abort
        rm -f "$CONFIRM_WAIT" "$CONFIRM_YES" "$FPGA_STEP_OUT"
        # The FPGA may have changed (Qvue-New/FPGA-Flash runs this too):
        # refresh OTA-FPGA once the locks are released.
        [ "${OTA_RECHECK:-1}" = 1 ] && setsid ./ota-check.sh fpga --wait </dev/null >/dev/null 2>&1 &
    fi
    [ "$(cat "$SYSTEM_LOCK" 2>/dev/null)" = "$$" ] && rm -f "$SYSTEM_LOCK"
    if [ "$ALS_WAS_ACTIVE" -eq 1 ]; then
        sudo -n systemctl start als-dimmer 2>/dev/null && log "als-dimmer started again"
    fi
}
trap cleanup EXIT

: > "$OTA_LOG"
push "$ID" running 0
log "start ($(date '+%F %T'))"

# A progress estimate for tools that report phases, not percentages:
# linear over <seconds>, never past 95 % until the tool has finished.
start_ticker() {
    local secs=$1
    ( t0=$SECONDS
      while sleep 1; do
          p=$(( (SECONDS - t0) * 95 / secs )); [ "$p" -gt 95 ] && p=95
          push_progress "$ID" "$p"
      done ) &
    TICKER=$!
}

# ---- board firmware ------------------------------------------------------------
update_iocs() {
    local want_board=$1 secs=$2 out line image a b rc
    out=$(iocs_check)
    line=$(printf '%s\n' "$out" | awk -v w="$want_board" '{
        for (i = 2; i <= NF; i++) if ($i ~ /^board=/) { split($i, kv, "="); if ((w == "ioc" && (kv[2] == "ots" || kv[2] == "qvue")) || kv[2] == w) print } }' | head -1)
    [ -n "$line" ] || fail "update-iocs.sh --check reports no $want_board board"
    [ "$(result_field "$line" status)" = outdated ] || \
        fail "nothing to update: $(result_field "$line" status) ($line)"
    image=$(result_field "$line" image)
    [ -n "$image" ] && [ "$image" != - ] || fail "no image for $want_board in $BIOS_DIR"
    a="$BIOS_DIR/$image"
    b="$BIOS_DIR/${image%_ota.bin}_otaB.bin"
    [ -r "$a" ] || fail "missing $a"
    log "$line"

    local args=()
    local power_cycle=1
    if [ "$want_board" = ioc ] && is_qvue_display_manager; then
        args=(--qvue "$a")
        [ -r "$b" ] && args+=(--qvue-b "$b")
        args+=(--warm)
        power_cycle=0
    elif [ "$want_board" = ioc ]; then
        args=(--ots "$a")
        [ -r "$b" ] && args+=(--ots-b "$b")
        args+=(--keep-stream)
    else
        args=(--983 "$a")
        [ -r "$b" ] && args+=(--983-b "$b")
    fi
    log "update-iocs.sh ${args[*]}"
    start_ticker "$secs"
    as_root "$UPDATE_IOCS" "${args[@]}" >>"$OTA_LOG" 2>&1
    rc=$?
    kill "$TICKER" 2>/dev/null; TICKER=""
    case $rc in
        0)  if [ "$power_cycle" -eq 1 ]; then
                echo "Power cycle required" > "$NOTICE_FILE" 2>/dev/null
                log "updated; a power cycle is required"
            else
                log "updated (warm: no power cycle needed)"
            fi ;;
        2)  fail "the update did not finish; the board is still usable (retry)" ;;
        3)  fail "the update must be repeated now (exit 3)" ;;
        4)  fail "the new firmware was rolled back (exit 4)" ;;
        5)  fail "refused: this image was rolled back before (exit 5)" ;;
        6)  fail "a board stopped answering: power cycle, then check (exit 6)" ;;
        *)  fail "update-iocs.sh exit $rc" ;;
    esac
}

# ---- QVue FPGA -----------------------------------------------------------------
FPGA_GOLDEN="3xqvue.bin"           # GOLDEN 0xD7, flash address 0, jumps to the UPDATE slot
FPGA_VENDOR="3xqvue-legacy.bin"    # the vendor image, byte-identical to delivered units
FPGA_MIN_MCU=0103                  # display_manager v01.03: the golden arm on the direct path
CONFIRM_SEC=${OTA_CONFIRM_SEC:-60}
SESSION_OPEN=0                     # a direct session this run opened and not closed
WRITING=0                          # 1 once a write began: a failure leaves the session open

# fpgaflash <bar from> <bar span> <value>: disptool fpgaflash, its output into
# the log and $FPGA_STEP_OUT, its erase / program / verify percentages mapped
# onto <from>..<from + span> of the key's bar (span 0: no bar). disptool's status.
fpgaflash() {
    local from=$1 span=$2 value=$3 rc
    : > "$FPGA_STEP_OUT"
    set -o pipefail
    stdbuf -oL -eL "$DISPTOOL" --device=ioc --command=fpgaflash --value="$value" 2>&1 \
      | strip_ansi | tr '\r' '\n' | tee -a "$FPGA_STEP_OUT" \
      | while IFS= read -r line; do
            printf '%s\n' "$line" >>"$OTA_LOG"
            [ "$span" -gt 0 ] || continue
            for tok in $(printf '%s\n' "$line" | grep -o -E '(erase|program|verify) [0-9]+ %' | tr ' ' '_'); do
                pct=${tok#*_}; pct=${pct%_%}
                case $tok in
                    erase_*)   pct=$(( pct * 5 / 100 )) ;;
                    program_*) pct=$(( 5 + pct * 90 / 100 )) ;;
                    verify_*)  pct=$(( 95 + pct * 5 / 100 )) ;;
                esac
                pct=$(( from + pct * span / 100 ))
                if [ "$pct" != "${last:-}" ]; then push_progress "$ID" "$pct"; last=$pct; fi
            done
        done
    rc=$?
    set +o pipefail
    return $rc
}

# Close the direct session this run opened (nothing written, or nothing to keep).
fpga_abort() {
    "$DISPTOOL" --device=ioc --command=fpgaflash --value=abort 2>&1 | strip_ansi >>"$OTA_LOG"
    SESSION_OPEN=0
}

# The display_manager version as four digits, e.g. 0110 for v01.10 ("" if none).
mcu_version() {
    timeout 5 "$DISPTOOL" --device=ioc --command=iocversion 2>/dev/null | strip_ansi \
        | sed -n 's/^FW Version *: *v\([0-9][0-9]*\)\.\([0-9][0-9]*\).*/\1\2/p' | head -1
}

# The FPGA as display_manager sees it: F_LINK (0x01, 0x00, ... or ?), F_IMAGE
# (the IDENTIFY image byte or ?), F_GOLDEN (1: "the GOLDEN image is running"),
# F_ENGINE (1: the image has the OTA engine, PPSPI page 1).
fpga_read() {
    local out
    out=$(timeout 10 "$DISPTOOL" --device=ioc --command=fpgaident 2>&1 | strip_ansi)
    F_LINK=$(printf '%s\n' "$out" | sed -n 's/^FPGA link *: *0x\([0-9A-Fa-f]*\).*/\1/p' | head -1)
    if [ -n "$F_LINK" ]; then F_LINK=0x$(printf '%s' "$F_LINK" | tr a-f A-F); else F_LINK="?"; fi
    F_IMAGE=$(printf '%s\n' "$out" | sed -n 's/^IDENTIFY *: *[0-9A-F ]*| *[0-9A-F][0-9A-F] [0-9A-F][0-9A-F] 00 \([0-9A-F][0-9A-F]\) |.*/\1/p' | head -1)
    F_IMAGE=${F_IMAGE:-?}
    F_GOLDEN=0; printf '%s\n' "$out" | grep -q 'the GOLDEN image is running' && F_GOLDEN=1
    F_ENGINE=0; printf '%s\n' "$out" | grep -q -E '^ *pages *:.*=( [0-9])* 1( |$)' && F_ENGINE=1
}

fpga_describe() {
    printf 'link %s, image %s%s%s' "$F_LINK" "$F_IMAGE" \
        "$([ "$F_GOLDEN" = 1 ] && echo ' (GOLDEN running)')" \
        "$([ "$F_LINK" = 0x01 ] && [ "$F_ENGINE" = 0 ] && echo ' (no OTA engine)')"
}

# After a begin that failed: if the MCU could not read the flash's JEDEC ID,
# close the session (disptool leaves it open) and say what that means.
fpga_flash_silent_check() {
    local line id
    line=$(grep -m1 'flash id is not 9D 60 18' "$FPGA_STEP_OUT") || return 0
    fpga_abort
    id=$(printf '%s\n' "$line" | sed -n 's/.*(read 0x\(..\) 0x\(..\) 0x\(..\)).*/\1 \2 \3/p')
    fail "the FPGA config flash did not answer (ID ${id:-not read}, expected 9D 60 18; FU_ERR 0x02). Nothing was written. Power-cycle the QVue fully (remove its supply) and run the update again; if it persists: hardware / JTAG"
}

# fpga_holds <file> <addr>, in the open direct session: 0 the flash at <addr>
# verifies as <file>, 1 it does not, 2 no verdict.
fpga_holds() {
    fpgaflash 0 0 "verify:$1,$2,direct"
    grep -q -E '^verify 0x[0-9A-Fa-f]+\+[0-9]+: flash CRC-32 0x[0-9A-Fa-f]+, file 0x[0-9A-Fa-f]+ +MATCH' "$FPGA_STEP_OUT" && return 0
    grep -q -E '^verify .* MISMATCH' "$FPGA_STEP_OUT" && return 1
    return 2
}

# fpga_confirm <question>: the key turns amber and asks; 0 = yes (the key held
# again within CONFIRM_SEC), 1 = no answer.
fpga_confirm() {
    rm -f "$CONFIRM_YES"
    echo "$$ $ID" > "$CONFIRM_WAIT" || return 1
    push "$ID" confirm
    log "$1"
    log "waiting $CONFIRM_SEC s: hold the key again = yes. About 10 min with the display off; keep the QVue powered (a power loss while GOLDEN is written leaves the FPGA dark until this is run again; no JTAG needed)"
    for _ in $(seq 1 $(( CONFIRM_SEC * 2 ))); do
        [ -e "$CONFIRM_YES" ] && break
        sleep 0.5
    done
    rm -f "$CONFIRM_WAIT"
    if [ -e "$CONFIRM_YES" ]; then
        rm -f "$CONFIRM_YES"
        push "$ID" running 4
        log "answer: yes"
        return 0
    fi
    log "answer: none within $CONFIRM_SEC s"
    return 1
}

update_fpga() {
    local want ver golden_file update_file vendor_file found rc done_ms from span
    is_qvue_display_manager || \
        fail "the QVue MCU does not run display_manager: update the MCU first (OTA-IOC, or Qvue-New/IOC-Flash for the stock firmware)"
    ver=$(mcu_version)
    { [ -n "$ver" ] && [ $(( 10#$ver )) -ge $(( 10#$FPGA_MIN_MCU )) ]; } || \
        fail "display_manager ${ver:+v${ver:0:2}.${ver:2} }is older than v01.03 (no GOLDEN arm): update the MCU first (OTA-IOC; release 1.24 = v01.10 recommended)"
    want=$(qvue_fpga_expected)
    [ -n "$want" ] || fail "no version for $QVUE_FPGA_UPDATE in $FPGA_MANIFEST"
    update_file="$FPGA_DIR/$QVUE_FPGA_UPDATE"
    golden_file="$FPGA_DIR/$FPGA_GOLDEN"
    vendor_file="$FPGA_DIR/$FPGA_VENDOR"
    for f in "$update_file" "$golden_file"; do [ -r "$f" ] || fail "missing $f"; done

    # Right after an MCU restart the link reads 0x00 until display_manager has
    # identified the FPGA: give it up to 30 s before deciding.
    fpga_read
    for _ in $(seq 1 10); do
        [ "$F_LINK" = 0x00 ] || break
        sleep 3; fpga_read
    done
    log "display_manager v${ver:0:2}.${ver:2}; FPGA $(fpga_describe); sp6bins ships 0x$want"

    local engine=0
    [ "$F_LINK" = 0x01 ] && [ "$F_ENGINE" = 1 ] && engine=1
    if [ "$engine" = 1 ] && [ "$F_IMAGE" = "$want" ] && [ "$F_GOLDEN" = 0 ] && [ "$FORCE" != 1 ]; then
        fail "nothing to update: image 0x$want already runs"
    fi

    if systemctl is-active --quiet als-dimmer 2>/dev/null; then
        ALS_WAS_ACTIVE=1
        sudo -n systemctl stop als-dimmer || log "could not stop als-dimmer"
    fi

    if [ "$engine" = 1 ]; then
        # A running pixelpipe image with the engine, GOLDEN included (the
        # recovery after a bad UPDATE slot): the slot only, display on.
        log "engine path: UPDATE slot 0x400000 <- $QVUE_FPGA_UPDATE (0x$want), display on"
        fpgaflash 0 97 "write:$update_file,0x400000,engine"; rc=$?
        [ "$rc" -eq 0 ] || \
            fail "fpgaflash engine write failed (exit $rc); the old image still runs: hold the key again to retry"
        # A write that resumed an open engine session verifies and leaves it
        # open with the old image running: end boots the new one.
        if grep -q 'LEFT OPEN' "$FPGA_STEP_OUT"; then
            fpgaflash 0 0 end || fail "the image was written and verified, but the FPGA did not come back from its boot"
        fi
    else
        # The vendor image (link 0x00 / 0x02 / 0xFF), a cut write, or an image
        # without the engine: the direct path. Start clean: an open session is
        # resumed in its own mode, so a direct write could go on as an engine one.
        log "direct path (FPGA $(fpga_describe)): display off, PROGRAM_B low"
        fpgaflash 0 0 abort || fail "could not close an open FPGA session (fpgaflash abort)"
        fpgaflash 0 0 begin; rc=$?
        if [ "$rc" -ne 0 ]; then
            fpga_flash_silent_check
            fpga_abort
            fail "the direct flash session did not open (fpgaflash begin exit $rc)"
        fi
        SESSION_OPEN=1
        push_progress "$ID" 2

        # What flash address 0 holds decides whether GOLDEN is written.
        fpga_holds "$golden_file" 0x0; rc=$?
        if [ "$rc" -eq 0 ]; then
            found=golden
        elif [ "$rc" -eq 2 ]; then
            fpga_abort; fail "verify of flash address 0 gave no verdict; nothing was written"
        elif [ -r "$vendor_file" ]; then
            fpga_holds "$vendor_file" 0x0; rc=$?
            case $rc in
                0) found=vendor ;;
                1) found=unknown ;;
                *) fpga_abort; fail "verify of flash address 0 gave no verdict; nothing was written" ;;
            esac
        else
            found=unknown
        fi
        log "flash address 0 holds: $found"
        push_progress "$ID" 4

        if [ "$found" = golden ]; then
            from=5; span=92
        else
            local question
            if [ "$found" = vendor ]; then
                question="Flash address 0 holds the vendor FPGA image, as delivered. It never starts the UPDATE slot, so an update alone would not run. Install our GOLDEN ($FPGA_GOLDEN) at address 0 once, then write the update?"
            else
                question="Flash address 0 holds neither our GOLDEN nor the vendor image: a GOLDEN write cut short, or an unknown image. Write our GOLDEN ($FPGA_GOLDEN) there, then the update?"
            fi
            if ! fpga_confirm "$question"; then
                fpga_abort
                fail "nothing was written: flash address 0 holds the $found image, which would boot instead of the update. Hold the key again and confirm to install GOLDEN"
            fi
            WRITING=1
            log "writing GOLDEN at flash address 0 (about 4.5 min)"
            fpgaflash 5 45 "write:$golden_file,0x0,golden"; rc=$?
            [ "$rc" -eq 0 ] || \
                fail "writing GOLDEN at flash address 0 failed (exit $rc). The display is off and the flash session is open: keep the QVue powered and hold the key again (an FPGA left dark by a cut GOLDEN write is recovered the same way, no JTAG needed)"
            from=50; span=47
        fi

        WRITING=1
        log "writing the UPDATE slot 0x400000 (about 4.5 min)"
        fpgaflash "$from" "$span" "write:$update_file,0x400000,direct"; rc=$?
        [ "$rc" -eq 0 ] || \
            fail "writing the UPDATE slot failed (exit $rc). The display is off and the flash session is open: keep the QVue powered and hold the key again"

        log "closing the session (PROGRAM_B released, the FPGA configures)"
        fpgaflash 0 0 end; rc=$?
        [ "$rc" -eq 0 ] || fail "fpgaflash end (exit $rc)"
        SESSION_OPEN=0
        # The MCU reports 0xFFFF when DONE never came.
        done_ms=$(sed -n 's/.*DONE after \([0-9][0-9]*\) ms.*/\1/p' "$FPGA_STEP_OUT" | head -1)
        if [ -z "$done_ms" ] || [ "$done_ms" -ge 65535 ]; then
            fail "the FPGA did not report DONE after fpgaflash end (${done_ms:-no DONE line}): it did not configure"
        fi
        log "FPGA configured (DONE after $done_ms ms)"
    fi

    # Exit status 0 does not mean the new image runs: the register link comes
    # back ~3 s after DONE, and a corrupt slot falls back to GOLDEN.
    push_progress "$ID" 97
    for _ in $(seq 1 15); do
        fpga_read
        [ "$F_LINK" = 0x01 ] && [ "$F_IMAGE" != "?" ] && break
        sleep 2
    done
    [ "$F_LINK" = 0x01 ] || fail "the image was written, but the FPGA does not answer since its boot ($(fpga_describe))"
    [ "$F_GOLDEN" = 0 ] || \
        fail "the image was written and verified, but the FPGA fell back to its GOLDEN image: the new UPDATE image did not start (hold the key again to rewrite it)"
    [ "$F_IMAGE" = "$want" ] || fail "the FPGA runs image 0x$F_IMAGE, expected 0x$want"
    log "FPGA runs image 0x$want${found:+ (address 0 was: $found)}"
}

# ---- system image ----------------------------------------------------------------
update_system() {
    local out ver running rundir data phase prog pct status
    [ -x "$AB_UPDATE" ] || fail "no ab-update engine on this image"
    out=$(as_root timeout 60 "$IMAGE_SCAN" 2>/dev/null)
    printf '%s\n' "$out" >>"$OTA_LOG"
    ver=$(printf '%s\n' "$out" | grep -m1 '^BUNDLE ' | tr ' ' '\n' | sed -n 's/^version=//p')
    running=$(printf '%s\n' "$out" | grep -m1 '^SUMMARY ' | tr ' ' '\n' | sed -n 's/^running=//p')
    printf '%s\n' "$out" | awk '
        /^BUNDLE / { n++; for (i = 2; i <= NF; i++) { split($i, kv, "="); b[kv[1]] = kv[2] } }
        /^SUMMARY / { for (i = 2; i <= NF; i++) { split($i, kv, "="); s[kv[1]] = kv[2] } }
        END { exit !(n == 1 && s["layout"] == "ab" && b["signature"] == "ok" && b["version"] != s["running"]) }' \
        || fail "no installable bundle on the stick (see $OTA_LOG)"
    rundir=$(ab_runtime_dir)
    status=$(sed -n 's/^state=//p' "$rundir/status" 2>/dev/null | head -1)
    [ "$status" != candidate-armed ] || fail "the running image is not committed yet"

    # System Manager's record, so its tab and the launcher badge can name the
    # install after the reboot (and after a fallback).
    data=$(system_manager_data)/logs/system-image-update
    mkdir -p "$data" 2>/dev/null
    printf 'version=%s\nfrom=%s\nstarted=%s\n' "$ver" "$running" "$(date -Iseconds)" \
        > "$data/last-install" 2>/dev/null
    log "installing $ver over $running: ab-update install usb"

    as_root "$AB_UPDATE" install usb >>"$OTA_LOG" 2>&1 &
    local engine=$!
    # Progress from the engine's progress file, as System Manager does
    while kill -0 "$engine" 2>/dev/null; do
        phase=$(sed -n 's/^phase=//p' "$rundir/progress" 2>/dev/null | head -1)
        prog=$(sed -n 's/^progress=//p' "$rundir/progress" 2>/dev/null | head -1)
        prog=${prog:-0}
        case "$phase" in
            validating) pct=1 ;; scanning) pct=2 ;; fetching) pct=3 ;; preparing) pct=4 ;;
            writing) pct=$(( 5 + prog * 88 / 100 )) ;;
            checking) pct=94 ;; boot-files) pct=97 ;; arming) pct=100 ;;
            failed-*) fail "the engine reports $phase" ;;
            *) pct="" ;;
        esac
        [ -n "$pct" ] && push_progress "$ID" "$pct"
        sleep 0.5
    done
    wait "$engine"
    local rc=$?
    phase=$(sed -n 's/^phase=//p' "$rundir/progress" 2>/dev/null | head -1)
    case "$phase" in
        failed-*) fail "the engine reports $phase (exit $rc)" ;;
    esac
    [ "$rc" -eq 0 ] || fail "ab-update install exit $rc"
    log "armed: the engine reboots into $ver"
}

case "$TARGET" in
    ioc)    update_iocs ioc 60 ;;
    983)    update_iocs 983 40 ;;
    fpga)   update_fpga ;;
    system) update_system ;;
esac

push "$ID" success
log "done"
exit 0
