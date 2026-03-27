#!/bin/bash
set -e

PREFIX="/usr/local"

for arg in "$@"; do
    case $arg in
        --prefix=*)  PREFIX="${arg#*=}" ;;
        -h|--help)
            echo "Usage: $0 [--prefix=PATH]"
            echo "  --prefix=PATH    Install prefix used during setup (default: /usr/local)"
            exit 0
            ;;
        *) echo "Unknown argument: $arg"; exit 1 ;;
    esac
done

[ "$(id -u)" -eq 0 ] || { echo "ERROR: uninstall.sh must be run as root (use sudo)"; exit 1; }

echo "[uninstall] streamdeck-ctrl uninstaller"

# Stop and disable service
echo "[1/5] Stopping and disabling service..."
systemctl stop streamdeck-ctrl 2>/dev/null || true
systemctl disable streamdeck-ctrl 2>/dev/null || true

# Remove systemd unit
echo "[2/5] Removing systemd unit..."
rm -f /etc/systemd/system/streamdeck-ctrl.service
systemctl daemon-reload

# Remove installed files
echo "[3/5] Removing installed files..."
rm -rf "${PREFIX}/lib/streamdeck-ctrl"
rm -rf "${PREFIX}/share/streamdeck-ctrl"
rm -f "${PREFIX}/bin/streamdeck-ctrl"

# Remove udev rule
echo "[4/5] Removing udev rule..."
rm -f /etc/udev/rules.d/99-streamdeck.rules
udevadm control --reload-rules 2>/dev/null || true

# Remove tmpfiles.d
echo "[5/5] Removing tmpfiles.d entry..."
rm -f /etc/tmpfiles.d/streamdeck-ctrl.conf
rm -rf /run/streamdeck-ctrl

echo ""
echo "[uninstall] Uninstallation complete."
echo "[uninstall] Config files in /etc/streamdeck-ctrl/ were NOT removed."
echo "[uninstall] To remove config: rm -rf /etc/streamdeck-ctrl/"
