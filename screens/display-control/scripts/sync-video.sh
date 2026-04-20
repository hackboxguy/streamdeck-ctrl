#!/bin/bash
# Sync video — recover FPD-Link deserializer for the currently
# configured display type. Maps HDMI timing type → --target value.
MICROPANEL_HOME="/home/pi/micropanel"
PI_CONFIG="$MICROPANEL_HOME/usr/bin/pi-config-txt.sh"
FPDLINK="$MICROPANEL_HOME/bin/fpdlink-tool.sh"
CONFIGS_PATH="$MICROPANEL_HOME/usr/share/micropanel/configs/"

CURRENT=$("$PI_CONFIG" --configspath="$CONFIGS_PATH" --input=/boot/firmware/config.txt 2>/dev/null)
CURRENT=$(echo "$CURRENT" | tr -d '[:space:]')

case "$CURRENT" in
    "12.3"|"14.6-fhd")
        TARGET=988
        ;;
    "12.3-nq1"|"14.6-2k5"|"15.6-2k5"|"17.3-3k"|"27")
        TARGET=984
        ;;
    "edid"|"edid-hdmi"|"unknown"|"")
        echo "[sync-video] Skipping (current=$CURRENT)"
        exit 0
        ;;
    *)
        echo "[sync-video] Unknown type '$CURRENT', skipping"
        exit 0
        ;;
esac

echo "[sync-video] current=$CURRENT → --target=$TARGET"
"$FPDLINK" --recover --target="$TARGET"
