#!/bin/bash
# Light the video key from the unit's real state, not from a remembered one.
#
# Runs from the service's ExecStartPost sync glob, so a deck plugged in after
# the fact shows what is actually on the panel.
set -u
. "$(dirname "$0")/cluster-env.sh"

if systemctl is-active --quiet cluster-video.service; then
    notify cluster.video on
else
    notify cluster.video off
fi
