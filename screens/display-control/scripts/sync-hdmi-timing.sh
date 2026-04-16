#!/bin/bash
# Sync current HDMI timing selection to streamdeck-ctrl radio buttons.
# Queries pi-config-txt.sh for the currently active HDMI timing profile
# and pushes notifications so only the matching button shows "on"
# (green border), all others show "off" (blue border).

MICROPANEL_HOME="/home/pi/micropanel"
PI_CONFIG="$MICROPANEL_HOME/usr/bin/pi-config-txt.sh"
CONFIGS_PATH="$MICROPANEL_HOME/usr/share/micropanel/configs/"
SOCK="/run/streamdeck-ctrl/notify.sock"
MAX_WAIT=10

# Wait for streamdeck-ctrl socket to appear
for i in $(seq 1 $MAX_WAIT); do
    [ -S "$SOCK" ] && break
    sleep 1
done

if [ ! -S "$SOCK" ]; then
    echo "[sync-hdmi] Timeout waiting for $SOCK"
    exit 0  # non-fatal
fi

# Check pi-config-txt.sh is available
if [ ! -x "$PI_CONFIG" ]; then
    echo "[sync-hdmi] pi-config-txt.sh not found, skipping"
    exit 0
fi

# Query current HDMI timing type
CURRENT=$("$PI_CONFIG" --configspath="$CONFIGS_PATH" --input=/boot/firmware/config.txt 2>/dev/null)
CURRENT=$(echo "$CURRENT" | tr -d '[:space:]')

if [ -z "$CURRENT" ] || [ "$CURRENT" = "unknown" ]; then
    echo "[sync-hdmi] Current HDMI timing is unknown, skipping"
    exit 0
fi

echo "[sync-hdmi] Current HDMI timing: $CURRENT"

# Map config type → streamdeck notification_id
# Only these three are currently wired up as buttons
declare -A TIMING_TO_ID=(
    ["12.3"]="hdmi.12_3_nq3"
    ["12.3-nq1"]="hdmi.12_3_nq1"
    ["15.6-2k5"]="hdmi.15_6_2k5"
    ["14.6-fhd"]="hdmi.14_6_fhd"
    ["edid"]="hdmi.edid"
)

# Push state for each known button: "on" for match, "off" for others
for timing in "${!TIMING_TO_ID[@]}"; do
    nid="${TIMING_TO_ID[$timing]}"
    if [ "$timing" = "$CURRENT" ]; then
        STATE="on"
    else
        STATE="off"
    fi
    echo "{\"id\":\"$nid\",\"state\":\"$STATE\"}" \
        | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
    echo "[sync-hdmi] $nid → $STATE"
done
