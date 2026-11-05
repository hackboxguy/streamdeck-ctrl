#!/bin/bash
# Check whether the OTA keys have something to do, and set them: "available"
# (yellow) when an update is there, "idle" (grey) otherwise. Read-only.
#
#   ota-check.sh [firmware] [fpga] [system] [--wait]
#
#   firmware  OTA-IOC and OTA-983: update-iocs.sh --check (two register reads
#             and a file read per board, about 0.2 s)
#   fpga      OTA-FPGA: the QVue FPGA's running image against the manifest
#   system    OTA-System: an installable .mpupdate on a USB stick
#   (none)    all three
#   --wait    while an update holds the locks, wait for it (up to 20 min)
#             instead of giving up; used after a flash
#
# Exit 0 when every check gave an answer, 75 when one could not (an update
# was running, or a board did not answer yet: the caller retries).
#
# A key that is running is never touched (an update holds the locks, and a
# check does not run then).

set -u
cd "$(dirname "$0")" || exit 1
. ./ota-lib.sh

WAIT=0
WANT=()
for a in "$@"; do
    case "$a" in
        firmware|fpga|system) WANT+=("$a") ;;
        --wait) WAIT=1 ;;
        *) echo "ota-check: unknown argument $a" >&2; exit 2 ;;
    esac
done
[ ${#WANT[@]} -gt 0 ] || WANT=(firmware fpga system)

if updates_busy; then
    [ "$WAIT" -eq 1 ] || exit 75
    for _ in $(seq 1 600); do
        sleep 2
        updates_busy || break
    done
    updates_busy && exit 75
fi

RC=0
inconclusive() { echo "ota-check: $*" >&2; RC=75; }

check_firmware() {
    local out line board status
    if [ ! -x "$UPDATE_IOCS" ] || [ ! -d "$BIOS_DIR" ]; then
        push "$ID_IOC" idle; push "$ID_983" idle
        return
    fi
    out=$(iocs_check)
    if [ -z "$out" ]; then
        inconclusive "update-iocs.sh --check gave no result"
        return
    fi
    while IFS= read -r line; do
        board=$(result_field "$line" board)
        status=$(result_field "$line" status)
        case "$board" in
            ots|qvue) id=$ID_IOC ;;
            983)      id=$ID_983 ;;
            *) continue ;;
        esac
        case "$status" in
            outdated)  push "$id" available ;;
            unknown)   inconclusive "$board: status unknown" ;;
            # uptodate, not-present, no-bootloader, no-image, ...: nothing
            # this key can do (a rolled-back image is never offered again)
            *)         push "$id" idle ;;
        esac
        echo "ota-check: $board $status"
    done <<< "$out"
}

check_fpga() {
    local ident link image want
    # QVue only for now: its FPGA is behind display_manager's bridge.
    if ! is_qvue_display_manager; then
        push "$ID_FPGA" idle
        echo "ota-check: fpga n/a (not a QVue running display_manager)"
        return
    fi
    want=$(qvue_fpga_expected)
    ident=$(qvue_fpga_ident)
    link=${ident% *}; image=${ident#* }
    case "$link" in
        0x01)
            if [ -z "$want" ]; then
                push "$ID_FPGA" idle
                echo "ota-check: fpga: no version for $QVUE_FPGA_UPDATE in the manifest"
            elif [ "$image" = "$want" ]; then
                push "$ID_FPGA" idle
                echo "ota-check: fpga 0x$image current"
            else
                push "$ID_FPGA" available
                echo "ota-check: fpga 0x$image, sp6bins ships 0x$want"
            fi ;;
        0x00) inconclusive "fpga link 0x00: not identified yet" ;;
        *)
            # vendor image (0xFF) or no answer: the engine needs a pixelpipe
            # image; that is the wire keys' job (Qvue-New/FPGA-Flash)
            push "$ID_FPGA" idle
            echo "ota-check: fpga link $link: not a pixelpipe image, no OTA" ;;
    esac
}

check_system() {
    local layout status out
    if [ ! -x "$AB_UPDATE" ] || [ ! -x "$IMAGE_SCAN" ]; then
        push "$ID_SYSTEM" idle
        return
    fi
    # The engine leaves this guard to the UI: no install while the running
    # image is still an uncommitted candidate.
    status=$(sed -n 's/^state=//p' "$(ab_runtime_dir)/status" 2>/dev/null | head -1)
    if [ "$status" = candidate-armed ]; then
        push "$ID_SYSTEM" idle
        echo "ota-check: system: running image not committed yet"
        return
    fi
    out=$(as_root timeout 60 "$IMAGE_SCAN" 2>/dev/null)
    if [ -z "$out" ]; then
        inconclusive "system-image-scan.sh gave no result"
        return
    fi
    # Exactly System Manager's offer rule (system-update-check.sh)
    if printf '%s\n' "$out" | awk '
        /^BUNDLE / { n++; for (i = 2; i <= NF; i++) { split($i, kv, "="); b[kv[1]] = kv[2] } }
        /^SUMMARY / { for (i = 2; i <= NF; i++) { split($i, kv, "="); s[kv[1]] = kv[2] } }
        END { exit !(n == 1 && s["layout"] == "ab" && b["signature"] == "ok" && b["version"] != s["running"]) }'
    then
        push "$ID_SYSTEM" available
        echo "ota-check: system: $(printf '%s\n' "$out" | grep -m1 '^BUNDLE ' | tr ' ' '\n' | grep '^version=') on the stick"
    else
        push "$ID_SYSTEM" idle
        echo "ota-check: system: nothing to install"
    fi
}

for w in "${WANT[@]}"; do
    "check_$w"
done
exit "$RC"
