#!/bin/bash
# Cluster Demo V2 with a theme: start the launcher's cluster-v2-<theme> tile.
# $1 = analog | ev | harman | fable1 | tiles | atelier | neo | auto
#
# Another app running (another theme, the old cluster, a video) is stopped
# first and the launcher's home awaited, as launch-cluster-demo.sh does: a
# direct app-to-app switch can leave the display undefined. The theme keys
# light from the launcher's running app (state_watch), so nothing is
# notified here.
LAUNCHER="${LAUNCHER_CLIENT:-/home/pi/micropanel/usr/bin/launcher-client}"
SRV="127.0.0.1:8081"

case "${1:-}" in
    analog|ev|harman|fable1|tiles|atelier|neo|auto) TILE="cluster-v2-$1" ;;
    *) echo "cluster-theme: unknown theme '${1:-}'" >&2; exit 2 ;;
esac

running() { "$LAUNCHER" --srv="$SRV" --command=get-running-app 2>/dev/null; }

RUNNING=$(running)
[ "$RUNNING" = "$TILE" ] && exit 0
if [ -n "$RUNNING" ] && [ "$RUNNING" != none ]; then
    "$LAUNCHER" --srv="$SRV" --command=stop-app
    for _ in $(seq 1 40); do                 # up to 10 s for the app to end
        [ "$(running)" = none ] && break
        sleep 0.25
    done
    [ "$(running)" = none ] || { echo "cluster-theme: $RUNNING did not stop" >&2; exit 1; }
    sleep 0.5
fi
"$LAUNCHER" --srv="$SRV" --command=start-app --command-arg="$TILE"
echo "cluster-theme: $TILE"
