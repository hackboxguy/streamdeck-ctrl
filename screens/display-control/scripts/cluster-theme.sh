#!/bin/bash
# Cluster Demo V2 with a theme: start the launcher's cluster-v2-<theme> tile.
# $1 = analog | ev | harman | fable1 | tiles | atelier | neo | auto
#
# Another app running (another theme, the old cluster, a video) is stopped
# first and the launcher's home awaited: a
# direct app-to-app switch can leave the display undefined. The theme keys
# light from the launcher's running app (state_watch), so nothing is
# notified here.
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
. "$DIR/launcher-lib.sh"

case "${1:-}" in
    analog|ev|harman|fable1|tiles|atelier|neo|auto) TILE="cluster-v2-$1" ;;
    *) echo "cluster-theme: unknown theme '${1:-}'" >&2; exit 2 ;;
esac

RUNNING=$(launcher_app)
[ "$RUNNING" = "$TILE" ] && exit 0
if [ "$RUNNING" != none ]; then
    launcher_stop_app || { echo "cluster-theme: ${RUNNING:-the running app} did not stop" >&2; exit 1; }
    sleep 0.5
fi
out=$(launcher_cmd start-app "$TILE")
case "$out" in
    OK*) echo "cluster-theme: $TILE" ;;
    *) echo "cluster-theme: the launcher did not start $TILE: $out" >&2; exit 1 ;;
esac
