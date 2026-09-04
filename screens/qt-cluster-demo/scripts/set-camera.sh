#!/bin/bash
# Show or hide the DMS live camera box. The NCAP telltales keep working
# either way -- only the video window is affected.
# $1 = new state, "on" or "off" (the toggle key flips before calling).
set -e
cd "$(dirname "$0")"; . ./cluster-env.sh

case "$1" in
    on|off) STATE="$1" ;;
    *) echo "usage: $0 on|off" >&2; exit 2 ;;
esac

BASE="$(cluster_args_without dms-video-view)"
write_cluster_args "$BASE --dms-video-view=$STATE"
./sync-cluster-state.sh
