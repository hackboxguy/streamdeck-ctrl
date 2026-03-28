#!/bin/bash
# Decrease display brightness by 10%, clamped to 0
ALS_CLIENT="/home/pi/als-dimmer/bin/als-dimmer-client"
CURRENT=$("$ALS_CLIENT" --brightness)
# Guard against empty/non-numeric response
if ! [[ "$CURRENT" =~ ^[0-9]+$ ]]; then
    exit 0
fi
NEW=$(( CURRENT - 10 ))
[ "$NEW" -lt 0 ] && NEW=0
"$ALS_CLIENT" --brightness=$NEW
