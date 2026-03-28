#!/bin/bash
# Called by als-dimmer on state change: $1=event_type $2=value
# Configure in als-dimmer: "on_change_script": "/home/pi/streamdeck-ctrl/screens/display-control/scripts/als-dimmer-notify.sh"

SOCK="/run/streamdeck-ctrl/notify.sock"

case "$1" in
    mode_changed)
        if [ "$2" = "auto" ]; then
            STATE="on"
        else
            STATE="off"
        fi
        echo "{\"id\":\"display.als_adaptive\",\"state\":\"$STATE\"}" \
            | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
        ;;
    brightness_changed)
        echo "{\"id\":\"display.brightness\",\"value\":\"$2\"}" \
            | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
        ;;
    zone_changed)
        echo "{\"id\":\"sensor.zone\",\"state\":\"$2\"}" \
            | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
        ;;
esac
