#!/bin/bash
# Toggle ALS adaptive brightness via als-dimmer-client
# $1 = new state ("on" or "off")
ALS_CLIENT="/home/pi/als-dimmer/bin/als-dimmer-client"

if [ "$1" = "on" ]; then
    "$ALS_CLIENT" --mode=auto
else
    "$ALS_CLIENT" --mode=manual
fi
