#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PREFIX="/usr/local"
CONFIG_FILE=""

usage() {
    echo "Usage: $0 --config=PATH [--prefix=PATH]"
    echo ""
    echo "  --config=PATH    Path to JSON layout config file (required)"
    echo "  --prefix=PATH    Install prefix (default: /usr/local)"
    echo ""
    echo "Must be run as root (sudo)."
    exit 1
}

for arg in "$@"; do
    case $arg in
        --config=*)  CONFIG_FILE="${arg#*=}" ;;
        --prefix=*)  PREFIX="${arg#*=}" ;;
        -h|--help)   usage ;;
        *) echo "Unknown argument: $arg"; usage ;;
    esac
done

[ -z "$CONFIG_FILE" ] && { echo "ERROR: --config is required"; usage; }
[ -f "$CONFIG_FILE" ] || { echo "ERROR: Config file not found: $CONFIG_FILE"; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo "ERROR: setup.sh must be run as root (use sudo)"; exit 1; }

# Verify Pi OS / Debian environment with systemd
if ! grep -qE "^ID=(raspbian|debian)" /etc/os-release 2>/dev/null; then
    echo "ERROR: This setup.sh targets Raspberry Pi OS Lite (Debian-based)."
    echo "       Detected OS does not match. Aborting."
    exit 1
fi
if ! systemctl --version >/dev/null 2>&1; then
    echo "ERROR: systemd not found. This script requires a systemd-based Pi OS."
    exit 1
fi

CONFIG_FILE="$(realpath "$CONFIG_FILE")"
CONFIG_DIR="$(dirname "$CONFIG_FILE")"
ICONS_DIR="${CONFIG_DIR}/icons"

echo "[setup] streamdeck-ctrl installer"
echo "[setup] Config: $CONFIG_FILE"
echo "[setup] Prefix: $PREFIX"
echo ""

# Step 2: System packages
echo "[1/9] Installing system packages..."
apt-get update -qq
apt-get install -y -qq libhidapi-hidraw0 libhidapi-libusb0 python3-pip socat

# Step 3: Python packages
echo "[2/9] Installing Python packages..."
pip3 install --quiet streamdeck pillow requests jsonschema

# Step 4+5: Install source
echo "[3/9] Installing streamdeck-ctrl source..."
mkdir -p "${PREFIX}/lib/streamdeck-ctrl"
cp -r "${SCRIPT_DIR}/streamdeck_ctrl/"*.py "${PREFIX}/lib/streamdeck-ctrl/"

# Install bundled font
mkdir -p "${PREFIX}/share/streamdeck-ctrl/fonts"
cp "${SCRIPT_DIR}/fonts/DejaVuSans-Bold.ttf" "${PREFIX}/share/streamdeck-ctrl/fonts/"

# Step 6: Wrapper binary
echo "[4/9] Installing streamdeck-ctrl binary..."
cat > "${PREFIX}/bin/streamdeck-ctrl" <<EOF
#!/bin/sh
exec python3 ${PREFIX}/lib/streamdeck-ctrl/main.py "\$@"
EOF
chmod 755 "${PREFIX}/bin/streamdeck-ctrl"

# Step 7: Config + icons
echo "[5/9] Installing config..."
mkdir -p /etc/streamdeck-ctrl/icons
if [ -f /etc/streamdeck-ctrl/layout.json ]; then
    cp /etc/streamdeck-ctrl/layout.json /etc/streamdeck-ctrl/layout.json.bak
    echo "[setup] Backed up existing config to layout.json.bak"
fi
cp "$CONFIG_FILE" /etc/streamdeck-ctrl/layout.json
if [ -d "$ICONS_DIR" ]; then
    cp -r "${ICONS_DIR}/." /etc/streamdeck-ctrl/icons/
    echo "[setup] Copied icons from $ICONS_DIR"
fi

# Step 8: udev rule
echo "[6/9] Installing udev rule..."
cp "${SCRIPT_DIR}/99-streamdeck.rules" /etc/udev/rules.d/
udevadm control --reload-rules
INSTALL_USER="${SUDO_USER:-pi}"
usermod -aG plugdev "$INSTALL_USER"
echo "[setup] Added $INSTALL_USER to plugdev group"

# Step 9: tmpfiles.d
echo "[7/9] Creating runtime directory..."
echo "d /run/streamdeck-ctrl 0755 root root -" \
    > /etc/tmpfiles.d/streamdeck-ctrl.conf
systemd-tmpfiles --create /etc/tmpfiles.d/streamdeck-ctrl.conf

# Step 10: systemd service
echo "[8/9] Installing and enabling systemd service..."
cp "${SCRIPT_DIR}/streamdeck-ctrl.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable streamdeck-ctrl
systemctl start streamdeck-ctrl || true   # don't fail if deck not plugged in yet

# Step 11: Status
echo "[9/9] Done. Current service status:"
echo ""
systemctl status streamdeck-ctrl --no-pager || true
echo ""
echo "[setup] Installation complete."
echo "[setup] Logs: journalctl -u streamdeck-ctrl -f"
echo "[setup] Notify socket: /run/streamdeck-ctrl/notify.sock"
