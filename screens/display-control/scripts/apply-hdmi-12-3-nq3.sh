#!/bin/bash
# Apply HDMI timing config for 12.3-nq3 display and reboot
# Note: maps to --type=12.3 (basic 12.3 type from HDMI Timing menu)
# pi-config-txt.sh edits /boot/firmware/config.txt and auto-reboots
MICROPANEL_HOME="/home/pi/micropanel"
sudo -n "$MICROPANEL_HOME/usr/bin/pi-config-txt.sh" \
    --configspath="$MICROPANEL_HOME/usr/share/micropanel/configs/" \
    --input=/boot/firmware/config.txt \
    --type=12.3
