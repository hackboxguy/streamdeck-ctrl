#!/bin/bash
# Set the deck's video keys without touching the video unit.
#   notify-video.sh off            -- both video keys off
#   notify-video.sh on [clip]      -- that clip's key on (default: the clip
#                                     cluster-video.env selects), the other off
#
# Called from cluster-video.service's ExecStopPost so that playback ending on
# its own -- an mpv crash, or a theme key restarting the cluster and tripping
# the bidirectional Conflicts= -- leaves the keys showing off rather than lit
# for a video that is no longer on screen.
set -u
. "$(dirname "$0")/cluster-env.sh"

if [ "${1:-off}" = "on" ]; then
    notify_video_keys "${2:-$(current_video_clip)}"
else
    notify_video_keys ""
fi
