#!/bin/bash
# Select the cluster's theme: legacy | ev | harman | fable1 | tiles
# The map backdrop is a separate key and is deliberately left alone here, so
# switching theme keeps whatever backdrop choice is in effect.
set -e
cd "$(dirname "$0")"; . ./cluster-env.sh

case "$1" in
    legacy) THEME="--theme=analog" ;;
    ev)     THEME="--theme=ev" ;;
    harman) THEME="--theme=harman" ;;
    fable1) THEME="--theme=fable1" ;;
    tiles)  THEME="--theme=tiles" ;;
    *) echo "usage: $0 legacy|ev|harman|fable1|tiles" >&2; exit 2 ;;
esac

# --theme=auto is what the proxy image ships; an explicit choice replaces it.
write_cluster_args "$(cluster_args_without theme) $THEME"
./sync-cluster-state.sh
