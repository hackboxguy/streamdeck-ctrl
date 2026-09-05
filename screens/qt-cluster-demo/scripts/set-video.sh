#!/bin/bash
# Start or stop full-screen video playback on the cluster panel.
#
# All the hard parts live in cluster-video.service, not here: it declares
# Conflicts=qt-cluster-demo.service, so systemd stops the cluster atomically
# when video starts, and its ExecStopPost brings the cluster back however
# playback ended -- stopped from this script, or crashed. That is why this
# script does not stop/start the cluster itself; a shell doing it by hand
# leaves a black screen if it is killed between the two halves.
set -u
. "$(dirname "$0")/cluster-env.sh"

UNIT="cluster-video.service"

case "${1:-}" in
    on)
        # Not "restart": if it is already playing, leave it alone.
        sudo -n systemctl start "$UNIT" || {
            echo "[cluster] failed to start $UNIT" >&2
            notify cluster.video off
            exit 1
        }
        echo "[cluster] video playing"
        notify cluster.video on
        ;;
    off)
        sudo -n systemctl stop "$UNIT"
        echo "[cluster] video stopped, cluster returning"
        notify cluster.video off
        ;;
    *)
        echo "usage: $(basename "$0") on|off" >&2
        exit 2
        ;;
esac
