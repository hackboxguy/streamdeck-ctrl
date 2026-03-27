#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE=""

usage() {
    echo "Usage: $0 --config=PATH"
    echo ""
    echo "  --config=PATH    Path to JSON layout config file (required)"
    echo ""
    echo "Everything runs from the repo directory — no files are copied"
    echo "to system paths except the udev rule and systemd unit symlink."
    echo ""
    echo "Must be run as root (sudo)."
    exit 1
}

for arg in "$@"; do
    case $arg in
        --config=*)  CONFIG_FILE="${arg#*=}" ;;
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
INSTALL_USER="${SUDO_USER:-pi}"

echo "[setup] streamdeck-ctrl installer (in-repo)"
echo "[setup] Repo dir:  $SCRIPT_DIR"
echo "[setup] Config:    $CONFIG_FILE"
echo "[setup] User:      $INSTALL_USER"
echo ""

# Step 1: System packages
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y -qq libhidapi-hidraw0 libhidapi-libusb0 python3-pip socat

# Step 2: Python packages
echo "[2/7] Installing Python packages..."
pip3 install --quiet streamdeck pillow requests jsonschema

# Step 3: Resolve {INSTALL_DIR} in the config file
echo "[3/7] Resolving {INSTALL_DIR} in config..."
if grep -q '{INSTALL_DIR}' "$CONFIG_FILE"; then
    sed -i "s|{INSTALL_DIR}|${SCRIPT_DIR}|g" "$CONFIG_FILE"
    echo "[setup] Replaced {INSTALL_DIR} → $SCRIPT_DIR in $CONFIG_FILE"
else
    echo "[setup] No {INSTALL_DIR} placeholders found in config (already resolved or not used)"
fi

# Step 4: Make scripts executable
echo "[4/7] Setting script permissions..."
CONFIG_DIR="$(dirname "$CONFIG_FILE")"
if [ -d "${CONFIG_DIR}/scripts" ]; then
    chmod +x "${CONFIG_DIR}/scripts/"*.sh 2>/dev/null || true
    echo "[setup] Made scripts in ${CONFIG_DIR}/scripts/ executable"
fi

# Step 5: udev rule
echo "[5/7] Installing udev rule..."
cp "${SCRIPT_DIR}/99-streamdeck.rules" /etc/udev/rules.d/
udevadm control --reload-rules
usermod -aG plugdev "$INSTALL_USER"
echo "[setup] Added $INSTALL_USER to plugdev group"

# Step 6: tmpfiles.d (runtime dir for Unix socket)
echo "[6/7] Creating runtime directory..."
echo "d /run/streamdeck-ctrl 0755 ${INSTALL_USER} plugdev -" \
    > /etc/tmpfiles.d/streamdeck-ctrl.conf
systemd-tmpfiles --create /etc/tmpfiles.d/streamdeck-ctrl.conf

# Step 7: Generate and install systemd service
echo "[7/7] Installing systemd service..."
sed -e "s|{INSTALL_DIR}|${SCRIPT_DIR}|g" \
    -e "s|{USER}|${INSTALL_USER}|g" \
    -e "s|{CONFIG_PATH}|${CONFIG_FILE}|g" \
    "${SCRIPT_DIR}/streamdeck-ctrl.service.in" \
    > /etc/systemd/system/streamdeck-ctrl.service
systemctl daemon-reload
systemctl enable streamdeck-ctrl
systemctl start streamdeck-ctrl || true   # don't fail if deck not plugged in yet

echo ""
systemctl status streamdeck-ctrl --no-pager || true
echo ""
echo "[setup] Installation complete."
echo "[setup] Logs:   journalctl -u streamdeck-ctrl -f"
echo "[setup] Socket: /run/streamdeck-ctrl/notify.sock"
echo "[setup] Config: $CONFIG_FILE"
echo ""
echo "[setup] NOTE: You may need to log out and back in for the 'plugdev'"
echo "[setup]       group membership to take effect."
