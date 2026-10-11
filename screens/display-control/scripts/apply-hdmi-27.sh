#!/bin/bash
# Apply HDMI timing config for 27" display and reboot
# pi-config-txt.sh edits /boot/firmware/config.txt and auto-reboots
MICROPANEL_HOME="/home/pi/micropanel"
sudo -n "$MICROPANEL_HOME/usr/bin/pi-config-txt.sh" \
    --configspath="$MICROPANEL_HOME/usr/share/micropanel/configs/" \
    --input=/boot/firmware/config.txt \
    --type=27
