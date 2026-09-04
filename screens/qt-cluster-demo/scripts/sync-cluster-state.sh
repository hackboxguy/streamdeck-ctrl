#!/bin/bash
# Push the cluster's actual configuration to the deck, so the four theme
# radios and the camera toggle show what is really running -- after a boot,
# after a change made over ssh, or after the deck is re-plugged.
#
# Radio keys never light themselves on press; this is the only thing that
# sets them.
cd "$(dirname "$0")"; . ./cluster-env.sh

# Wait for the notification socket (the daemon may still be starting).
for _ in $(seq 1 10); do
    [ -S "$SOCK" ] && break
    sleep 1
done
[ -S "$SOCK" ] || { echo "[sync-cluster] no $SOCK, giving up"; exit 0; }

ARGS="$(cluster_args)"
if [ -z "$ARGS" ]; then
    echo "[sync-cluster] no CLUSTER_ARGS in $ENV_FILE"
    exit 0
fi

theme=$(echo "$ARGS" | grep -oE -- '--theme=[a-z]+' | head -1 | cut -d= -f2)
map=$(echo "$ARGS"   | grep -oE -- '--harman-map=[a-z]+' | head -1 | cut -d= -f2)
cam=$(echo "$ARGS"   | grep -oE -- '--dms-video-view=[a-z]+' | head -1 | cut -d= -f2)

# Defaults match the application's own: map on, camera on.
[ -z "$map" ] && map="on"
[ -z "$cam" ] && cam="on"

# --theme=auto follows the vehicle, so no fixed key represents it; all four
# radios stay off rather than claiming a selection the vehicle may change.
selected=""
case "$theme" in
    analog) selected="cluster.theme_legacy" ;;
    ev)     selected="cluster.theme_ev" ;;
    harman) [ "$map" = "on" ] && selected="cluster.theme_harman_map" \
                              || selected="cluster.theme_harman" ;;
esac

for id in cluster.theme_legacy cluster.theme_ev \
          cluster.theme_harman cluster.theme_harman_map; do
    if [ "$id" = "$selected" ]; then notify "$id" on; else notify "$id" off; fi
done
notify cluster.camera "$cam"

echo "[sync-cluster] theme=${theme:-unset} map=$map camera=$cam -> ${selected:-none}"
