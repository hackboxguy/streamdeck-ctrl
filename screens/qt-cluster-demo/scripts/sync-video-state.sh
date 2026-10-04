#!/bin/bash
# Light the video keys from the unit's real state, not from a remembered one.
#
# Runs from the service's ExecStartPost sync glob, so a deck plugged in after
# the fact shows what is actually on the panel: the key of the clip that is
# playing on, every other video key off.
set -u
. "$(dirname "$0")/cluster-env.sh"

if systemctl is-active --quiet cluster-video.service; then
    notify_video_keys "$(current_video_clip)"
else
    notify_video_keys ""
fi
