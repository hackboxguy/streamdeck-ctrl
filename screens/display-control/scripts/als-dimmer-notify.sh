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
        # The brightness key (live_value, display.brightness); covers changes
        # the keys did not make, e.g. disp-settings or ALS in AUTO mode. The
        # key also carries the backlight temperature: append the one
        # brightness-value.sh cached (no I2C read from als-dimmer's callback;
        # the next poll refreshes it).
        TEMP=$(head -n1 /tmp/streamdeck-bltemp.cache 2>/dev/null)
        echo "{\"id\":\"display.brightness\",\"value\":\"$2%${TEMP:+ $TEMP}\"}" \
            | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
        ;;
    # Uncomment below when a matching live_value/multistate key is added to display-control.json:
    # zone_changed)
    #     echo "{\"id\":\"sensor.zone\",\"state\":\"$2\"}" \
    #         | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
    #     ;;
esac
