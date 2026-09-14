#!/bin/bash
# Apply HDMI timing config for the 3x QVue 12in display and reboot
# 4500x298 over 988 dual OLDI (6.75Gbps), no touch controller
# pi-config-txt.sh edits /boot/firmware/config.txt and auto-reboots
MICROPANEL_HOME="/home/pi/micropanel"
sudo -n "$MICROPANEL_HOME/usr/bin/pi-config-txt.sh" \
    --configspath="$MICROPANEL_HOME/usr/share/micropanel/configs/" \
    --input=/boot/firmware/config.txt \
    --type=3x-qvue
