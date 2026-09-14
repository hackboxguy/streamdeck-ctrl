#!/bin/bash
# Apply HDMI timing config for 12.3-nq5 display and reboot
# Note: maps to --type=12.3 (basic 12.3 type from HDMI Timing menu) -- there is
# no separate 12.3-nq5 type in pi-config-txt.sh; the NQ5 panel runs the plain
# 12.3 timing. Only 12.3-nq1 needs its own entry.
# pi-config-txt.sh edits /boot/firmware/config.txt and auto-reboots
MICROPANEL_HOME="/home/pi/micropanel"
sudo -n "$MICROPANEL_HOME/usr/bin/pi-config-txt.sh" \
    --configspath="$MICROPANEL_HOME/usr/share/micropanel/configs/" \
    --input=/boot/firmware/config.txt \
    --type=12.3
