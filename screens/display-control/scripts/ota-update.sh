#!/bin/bash
# Run one OTA update for the page-6 OTA keys and report it to the deck:
# a blinking green border with a progress bar while it runs, then solid green
# (success) or red (failure). The key only lets this start when it is yellow
# ("available") or red (a retry), after a 1.5 s hold.
#
#   ota-update.sh ioc|983|fpga|system
#
#   ioc     the display IOC: on a QVue running display_manager
#           update-iocs.sh --qvue A --qvue-b B --warm (no reset, no power
#           cycle); elsewhere --ots A --ots-b B --keep-stream (power cycle after)
#   983     the 983HH serializer board: update-iocs.sh --983 A --983-b B
#           (power cycle after: touch and the 983's setup come back with it)
#   fpga    the QVue FPGA's UPDATE slot: disptool fpgaflash
#           write:3xqvue-update.bin,0x400000,engine (display on; about 2.5 s
#           dark at the end when the new image boots)
#   system  the .mpupdate on the USB stick: ab-update install usb (the engine
#           verifies, writes the inactive slot and reboots by itself)
#
# The images come from the same --check System Manager runs (its image=
# column: the pair whose board code the board runs). Nothing is updated that
# the check does not call outdated, so a rolled-back image (update-iocs exit
# 5) is never installed again from here.
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
update_fpga() {
    local want ident file rc line pct
    is_qvue_display_manager || fail "not a QVue running display_manager"
    want=$(qvue_fpga_expected)
    [ -n "$want" ] || fail "no version for $QVUE_FPGA_UPDATE in $FPGA_MANIFEST"
    ident=$(qvue_fpga_ident)
    [ "${ident% *}" = 0x01 ] || fail "FPGA link ${ident% *}: the engine needs a running pixelpipe image"
    # OTA_FORCE=1 (bench only): rewrite the slot although it already carries
    # this image, to exercise the path; the old image runs until the end.
    [ "${ident#* }" != "$want" ] || [ "${OTA_FORCE:-0}" = 1 ] || \
        fail "nothing to update: image 0x$want already runs"
    file="$FPGA_DIR/$QVUE_FPGA_UPDATE"
    [ -r "$file" ] || fail "missing $file"
    log "FPGA image 0x${ident#* } -> 0x$want ($file)"

    if systemctl is-active --quiet als-dimmer 2>/dev/null; then
        ALS_WAS_ACTIVE=1
        sudo -n systemctl stop als-dimmer || log "could not stop als-dimmer"
    fi
    # disptool prints "erase N %", "program N %", "verify N %" as it goes:
    # erase 0-5, program 5-95, verify 95-100.
    set -o pipefail
    stdbuf -oL -eL "$DISPTOOL" --device=ioc --command=fpgaflash \
        --value="write:$file,0x400000,engine" 2>&1 | strip_ansi | tr '\r' '\n' \
      | while IFS= read -r line; do
            printf '%s\n' "$line" >>"$OTA_LOG"
            for tok in $(printf '%s\n' "$line" | grep -o -E '(erase|program|verify) [0-9]+ %' | tr ' ' '_'); do
                pct=${tok#*_}; pct=${pct%_%}
                case $tok in
                    erase_*)   pct=$(( pct * 5 / 100 )) ;;
                    program_*) pct=$(( 5 + pct * 90 / 100 )) ;;
                    verify_*)  pct=$(( 95 + pct * 5 / 100 )) ;;
                esac
                if [ "$pct" != "${last:-}" ]; then push_progress "$ID" "$pct"; last=$pct; fi
            done
        done
    rc=$?
    set +o pipefail
    [ "$rc" -eq 0 ] || fail "fpgaflash engine write failed (exit $rc); the old image still runs"
    for _ in $(seq 1 15); do
        ident=$(qvue_fpga_ident)
        [ "$ident" = "0x01 $want" ] && break
        sleep 2
    done
    [ "$ident" = "0x01 $want" ] || fail "after the update fpgaident shows '$ident' (want 0x01 $want)"
    log "FPGA runs image 0x$want"
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
