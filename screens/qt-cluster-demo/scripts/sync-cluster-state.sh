#!/bin/bash
# Push the cluster's actual configuration to the deck: which theme is running,
# and whether the map backdrop, the camera view and sharp lamps are on.
#
# Radio keys never light themselves on press, so this is the only thing that
# sets them -- after a boot, after a change made over ssh, or after the deck
# is re-plugged.
cd "$(dirname "$0")"; . ./cluster-env.sh

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
map=$(echo "$ARGS"   | grep -oE -- '--map-backdrop=[a-z]+' | head -1 | cut -d= -f2)
[ -z "$map" ] && map=$(echo "$ARGS" | grep -oE -- '--harman-map=[a-z]+' | head -1 | cut -d= -f2)
cam=$(echo "$ARGS"   | grep -oE -- '--dms-video-view=[a-z]+' | head -1 | cut -d= -f2)
glow=$(echo "$ARGS"  | grep -oE -- '--telltale-glow=[a-z]+' | head -1 | cut -d= -f2)

# Defaults match the application's own.
[ -z "$map" ] && map="on"
[ -z "$cam" ] && cam="on"
[ -z "$glow" ] && glow="on"

# The key is named for the look, so it is lit when the glow is off.
if [ "$glow" = "off" ]; then lamps="on"; else lamps="off"; fi

# --theme=auto follows the vehicle, so no fixed key represents it; all three
# radios stay off rather than claiming a selection the vehicle may change.
selected=""
case "$theme" in
    analog) selected="cluster.theme_legacy" ;;
    ev)     selected="cluster.theme_ev" ;;
    harman) selected="cluster.theme_harman" ;;
esac

for id in cluster.theme_legacy cluster.theme_ev cluster.theme_harman; do
    if [ "$id" = "$selected" ]; then notify "$id" on; else notify "$id" off; fi
done
notify cluster.map "$map"
notify cluster.camera "$cam"
notify cluster.lamps "$lamps"

echo "[sync-cluster] theme=${theme:-unset} map=$map camera=$cam sharp=$lamps -> ${selected:-none}"
