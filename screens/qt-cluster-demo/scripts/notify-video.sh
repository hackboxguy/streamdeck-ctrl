#!/bin/bash
# Set the deck's video key state without touching the video unit.
#
# Called from cluster-video.service's ExecStopPost so that playback ending on
# its own -- an mpv crash, or a theme key restarting the cluster and tripping
# the bidirectional Conflicts= -- leaves the key showing off rather than lit
# for a video that is no longer on screen.
set -u
. "$(dirname "$0")/cluster-env.sh"
notify cluster.video "${1:-off}"
