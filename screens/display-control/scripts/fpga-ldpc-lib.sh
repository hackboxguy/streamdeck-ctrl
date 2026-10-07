# Sourced by local-dimming-toggle.sh and pixel-compensation-toggle.sh: the
# LD/PC choice as every app with LD/PC buttons keeps it (their shared
# FpgaController), and the FPGA written the way that controller does.
#
# The file: /data/cluster/fpga-ldpc-state.json where /data/cluster exists
# (the A/B image: it survives power cycles), else /tmp/fpga-ldpc-state.json
# (this boot only). Replaced whole, 0644, owned like its directory (pi on
# /data/cluster; pi in /tmp, whose sticky bit would otherwise stop the apps,
# which run as pi, from replacing a root-owned file).
#
# The FPGA: through disptool, the new register slave (0x1E) whenever it
# answers at all - even with an odd VERSION, which disptool's own fpgaauto
# would answer with the legacy protocol, and legacy register 0x29 on a 0x1E
# bitstream is the OTA work-mode bit that locks register writes until a
# power cycle. Only an FPGA without 0x1E gets the legacy registers (LD 0x29,
# PC 0x47). The probe is one I2C_RDWR transaction (i2ctransfer).

DISPTOOL="${DISPTOOL:-/home/pi/micropanel/bin/disptool}"
I2CDEV="${I2CDEV:-/dev/i2c-1}"
SOCK="${STREAMDECK_SOCKET:-/run/streamdeck-ctrl/notify.sock}"
# shellcheck disable=SC2034 # used by the scripts that source this
LOCK_FILE="${FPGA_LDPC_LOCK_FILE:-/tmp/fpga-ldpc.lock}"
if [ -z "${FPGA_LDPC_STATE_FILE:-}" ]; then
    if [ -d "${FPGA_LDPC_DATA_DIR:-/data/cluster}" ]; then
        FPGA_LDPC_STATE_FILE="${FPGA_LDPC_DATA_DIR:-/data/cluster}/fpga-ldpc-state.json"
    else
        FPGA_LDPC_STATE_FILE=/tmp/fpga-ldpc-state.json
    fi
fi
STATE_FILE=$FPGA_LDPC_STATE_FILE

# fpganew or fpga (disptool's --device); fpgaauto only without i2ctransfer
fpga_device() {
    command -v i2ctransfer >/dev/null 2>&1 || { echo fpgaauto; return; }
    if i2ctransfer -y "${I2CDEV#/dev/i2c-}" w2@0x1e 0x00 0x00 r1 >/dev/null 2>&1; then
        echo fpganew
    else
        echo fpga
    fi
}

notify_key() { # <notification id> <state>
    [ -S "$SOCK" ] || return 0
    printf '{"id":"%s","state":"%s"}\n' "$1" "$2" \
        | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1 || true
}

# save_choice <local_dimming|pixel_compensation> <on|off> <fpganew|fpga|fpgaauto>
save_choice() {
    python3 - "$STATE_FILE" "$1" "$2" "$3" <<'PY'
import json, os, pwd, stat, sys, tempfile

path, field, requested, device = sys.argv[1:5]
state = {"version": 1, "local_dimming": True, "pixel_compensation": True}
try:
    with open(path) as existing:
        loaded = json.load(existing)
    if isinstance(loaded, dict):
        state.update(loaded)
except (OSError, ValueError, TypeError):
    pass
state["version"] = 1
# The protocol it was set on (the apps accept either; a swapped display keeps
# the choice). fpgaauto: unknown here, keep what was there.
if device in ("fpganew", "fpga"):
    state["protocol"] = "new" if device == "fpganew" else "legacy"
state.setdefault("protocol", "legacy")
state[field] = requested == "on"
for key in ("local_dimming", "pixel_compensation"):
    state[key] = bool(state.get(key, True))

directory = os.path.dirname(path) or "."
fd, temporary = tempfile.mkstemp(prefix=".fpga-ldpc-", dir=directory)
try:
    with os.fdopen(fd, "w") as output:
        json.dump(state, output, separators=(",", ":"))
        output.flush()
        os.fsync(output.fileno())
    os.chmod(temporary, 0o644)
    if os.geteuid() == 0:
        info = os.stat(directory)
        if info.st_mode & stat.S_ISVTX:          # /tmp: the apps' account
            try:
                owner = pwd.getpwnam(os.environ.get("FPGA_LDPC_OWNER", "pi"))
                os.chown(temporary, owner.pw_uid, owner.pw_gid)
            except KeyError:
                pass
        else:
            os.chown(temporary, info.st_uid, info.st_gid)
    os.replace(temporary, path)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
}

# set_fpga <localdim|pixelcomp> <on|off> <device>
set_fpga() {
    "$DISPTOOL" --i2cdev="$I2CDEV" --device="$3" --command="$1" --value="$2"
}
