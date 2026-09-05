#!/bin/bash
# Show or hide the navigation map backdrop. It applies to whichever theme is
# selected, so this is orthogonal to the three theme keys.
# $1 = new state, "on" or "off" (the toggle key flips before calling).
set -e
cd "$(dirname "$0")"; . ./cluster-env.sh

case "$1" in
    on|off) STATE="$1" ;;
    *) echo "usage: $0 on|off" >&2; exit 2 ;;
esac

# --harman-map is the old spelling and still accepted by the app; drop it too
# so an image built before the rename cannot end up with both.
write_cluster_args "$(cluster_args_without map-backdrop harman-map) --map-backdrop=$STATE"
./sync-cluster-state.sh
