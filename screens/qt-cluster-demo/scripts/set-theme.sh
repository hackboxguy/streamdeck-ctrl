#!/bin/bash
# Select the cluster's theme: legacy | ev | harman | harman-map
# Rewrites CLUSTER_ARGS and restarts the unit, so the choice persists.
set -e
cd "$(dirname "$0")"; . ./cluster-env.sh

case "$1" in
    legacy)     THEME="--theme=analog" ;;
    ev)         THEME="--theme=ev" ;;
    harman)     THEME="--theme=harman --harman-map=off" ;;
    harman-map) THEME="--theme=harman --harman-map=on" ;;
    *) echo "usage: $0 legacy|ev|harman|harman-map" >&2; exit 2 ;;
esac

# --theme=auto is what the proxy image ships; an explicit choice replaces it.
BASE="$(cluster_args_without theme harman-map)"
write_cluster_args "$BASE $THEME"
./sync-cluster-state.sh
