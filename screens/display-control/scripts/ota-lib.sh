# Sourced by ota-check.sh and ota-update.sh: the OTA keys on page 6 (OTA-IOC,
# OTA-983, OTA-FPGA, OTA-System), done with the same tools and rules as the
# System Manager app (br-wrapper system-manager-app), so the two never disagree:
#
#   board firmware   update-iocs.sh --check --image-dir <bios-bin>   (read-only)
#                    update-iocs.sh --qvue A --qvue-b B --warm      (QVue IOC)
#                    update-iocs.sh --ots A --ots-b B --keep-stream (other IOCs)
#                    update-iocs.sh --983 A --983-b B               (983HH)
#   QVue FPGA        the running IDENTIFY image byte against the manifest's
#                    version of 3xqvue-update.bin; disptool fpgaflash
#                    write:<file>,0x400000,engine (display stays on)
#   system image     system-image-scan.sh (read-only, mounts the stick ro);
#                    ab-update install usb (reboots by itself)
#
# Keys: task keys with a yellow "available" state; idle = nothing to do (grey).
# One I2C user at a time: an update holds /tmp/target-flash.lock (every flash
# script and the deck's pollers respect it) and System Manager's
# /tmp/system-update.lock (pid inside; its badge and the app respect it), and
# a check never runs while either is held.

MICROPANEL_HOME="${MICROPANEL_HOME:-/home/pi/micropanel}"
BIN="$MICROPANEL_HOME/bin"
DISPTOOL="$BIN/disptool"
UPDATE_IOCS="$BIN/update-iocs.sh"
IMAGE_SCAN="$BIN/system-image-scan.sh"
SP6BINS="$MICROPANEL_HOME/share/sp6bins"
BIOS_DIR="$SP6BINS/firmware/bios-bin"
FPGA_DIR="$SP6BINS/firmware/fpga"
FPGA_MANIFEST="$FPGA_DIR/manifest.txt"
QVUE_FPGA_UPDATE="3xqvue-update.bin"
AB_UPDATE="${AB_UPDATE:-/usr/local/bin/ab-update}"
AB_CONF="${AB_UPDATE_CONFIG:-/usr/lib/pi-ab-update/ab-update.conf}"

SOCK="/run/streamdeck-ctrl/notify.sock"
FLASH_LOCK="/tmp/target-flash.lock"
SYSTEM_LOCK="/tmp/system-update.lock"
NOTICE_FILE="/tmp/micropanel-notice"
OTA_LOG="/tmp/ota-update.log"

ID_IOC="ota.ioc"
ID_983="ota.983"
ID_FPGA="ota.fpga"
ID_SYSTEM="ota.system"

strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }

as_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo -n "$@"; fi
}

# push <id> <state> [progress]
push() {
    [ -S "$SOCK" ] || return 0
    if [ -n "${3:-}" ]; then
        printf '{"id":"%s","state":"%s","value":"%s"}\n' "$1" "$2" "$3"
    else
        printf '{"id":"%s","state":"%s"}\n' "$1" "$2"
    fi | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1 || true
}

# push_progress <id> <0..100>
push_progress() {
    [ -S "$SOCK" ] || return 0
    printf '{"id":"%s","value":"%s"}\n' "$1" "$2" \
        | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1 || true
}

flash_lock_held() {
    [ -e "$FLASH_LOCK" ] && ! flock -n "$FLASH_LOCK" true 2>/dev/null
}

# System Manager (or an OTA key) is updating: its lock names a live pid.
system_lock_held() {
    local pid
    [ -e "$SYSTEM_LOCK" ] || return 1
    pid=$(cat "$SYSTEM_LOCK" 2>/dev/null)
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

updates_busy() { flash_lock_held || system_lock_held; }

# The display IOC's App Name and Board Name over 0x66 ("" when nothing answers).
ioc_app()   { timeout 3 "$DISPTOOL" --device=ioc --command=iocversion 2>/dev/null | strip_ansi \
                  | sed -n 's/^App Name *: *//p' | tr -d '[:space:]'; }
ioc_board() { timeout 3 "$DISPTOOL" --device=ioc --command=iocversion 2>/dev/null | strip_ansi \
                  | sed -n 's/^Board Name *: *//p' | tr -d '[:space:]'; }

is_qvue_display_manager() {
    [ "$(ioc_app)" = display_manager ] && [ "$(ioc_board)" = QVUE_9090 ]
}

# The QVue FPGA as display_manager sees it: "<link> <image>", e.g. "0x01 D9".
qvue_fpga_ident() {
    local out link image
    out=$(timeout 5 "$DISPTOOL" --device=ioc --command=fpgaident 2>/dev/null | strip_ansi)
    link=$(printf '%s\n' "$out" | sed -n 's/^FPGA link *: *\(0x[0-9A-Fa-f]*\).*/\1/p')
    image=$(printf '%s\n' "$out" | sed -n 's/^IDENTIFY *: *[0-9A-F ]*| *[0-9A-F][0-9A-F] [0-9A-F][0-9A-F] 00 \([0-9A-F][0-9A-F]\) |.*/\1/p')
    echo "${link:-?} ${image:-?}"
}

# The image byte sp6bins ships for the QVue's UPDATE slot, e.g. "D9" ("" if none).
qvue_fpga_expected() {
    awk -v f="$QVUE_FPGA_UPDATE" '/^file:/ {c=$2} c==f && /^version:/ {print $2; exit}' \
        "$FPGA_MANIFEST" 2>/dev/null | sed 's/^0[xX]//' | tr '[:lower:]' '[:upper:]'
}

# update-iocs.sh --check, once: its RESULT lines (as root, like System Manager).
iocs_check() {
    as_root timeout 60 "$UPDATE_IOCS" --check --image-dir "$BIOS_DIR" 2>/dev/null | grep '^RESULT '
}

# result_field <RESULT line> <key>
result_field() { printf '%s\n' "$1" | tr ' ' '\n' | sed -n "s/^$2=//p" | head -1; }

ab_runtime_dir() {
    local d
    d=$(awk 'index($0, "AB_RUNTIME_DIR=") == 1 { v = substr($0, 16) } END { print v }' "$AB_CONF" 2>/dev/null)
    echo "${d:-/run/ab-update}"
}

# System Manager's durable directory (logs, last-install).
system_manager_data() {
    local d="${SYSTEM_MANAGER_DATA:-/data/system-manager}"
    [ -d "$d" ] || d="$MICROPANEL_HOME/usr"
    echo "$d"
}
