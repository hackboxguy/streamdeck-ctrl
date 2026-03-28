#!/bin/bash
# Sync als-dimmer state to streamdeck-ctrl after startup.
# Called via ExecStartPost in streamdeck-ctrl.service.
# Waits for the notification socket, then queries als-dimmer
# and pushes current state to streamdeck-ctrl.

ALS_CLIENT="/home/pi/als-dimmer/bin/als-dimmer-client"
SOCK="/run/streamdeck-ctrl/notify.sock"
MAX_WAIT=10

# Wait for streamdeck-ctrl socket to appear
for i in $(seq 1 $MAX_WAIT); do
    [ -S "$SOCK" ] && break
    sleep 1
done

if [ ! -S "$SOCK" ]; then
    echo "[sync] Timeout waiting for $SOCK"
    exit 0  # non-fatal
fi

# Check als-dimmer is reachable
if ! "$ALS_CLIENT" --status > /dev/null 2>&1; then
    echo "[sync] als-dimmer not reachable, skipping sync"
    exit 0
fi

# Sync mode (auto → on, manual/manual_temporary → off)
MODE=$("$ALS_CLIENT" --mode 2>/dev/null)
if [ -n "$MODE" ]; then
    [ "$MODE" = "auto" ] && STATE="on" || STATE="off"
    echo "{\"id\":\"display.als_adaptive\",\"state\":\"$STATE\"}" \
        | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
    echo "[sync] ALS adaptive: $MODE → $STATE"
fi
