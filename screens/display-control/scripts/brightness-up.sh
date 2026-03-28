#!/bin/bash
# Increase display brightness by 10%, clamped to 100
ALS_CLIENT="/home/pi/als-dimmer/bin/als-dimmer-client"
CURRENT=$("$ALS_CLIENT" --brightness)
NEW=$(( CURRENT + 10 ))
[ "$NEW" -gt 100 ] && NEW=100
"$ALS_CLIENT" --brightness=$NEW
