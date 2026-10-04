#!/bin/bash
# Start, switch or stop full-screen video playback on the cluster panel.
#   set-video.sh [video1|video2] on|off      (clip defaults to video1)
#
# All the hard parts live in cluster-video.service, not here: it declares
# Conflicts=qt-cluster-demo.service, so systemd stops the cluster atomically
# when video starts, and its ExecStopPost brings the cluster back however
# playback ended -- stopped from this script, or crashed. That is why this
# script does not stop/start the cluster itself; a shell doing it by hand
# leaves a black screen if it is killed between the two halves.
#
# The two video keys are one group: pressing either one on plays its clip and
# turns the other key off, whatever was on screen before.
set -u
. "$(dirname "$0")/cluster-env.sh"

UNIT="cluster-video.service"

if [ $# -ge 2 ]; then CLIP="$1"; shift; else CLIP="video1"; fi
VIDEO_FILE="$(video_file_for "$CLIP")" || {
    echo "usage: $(basename "$0") [video1|video2] on|off" >&2
    exit 2
}

case "${1:-}" in
    on)
        if [ ! -r "$VIDEO_FILE" ]; then
            # Refuse before the unit's Conflicts= takes the cluster down.
            echo "[cluster] $VIDEO_FILE missing; was the image built with media-files?" >&2
            notify "$(video_key_for "$CLIP")" off
            exit 1
        fi
        write_video_file "$VIDEO_FILE" || { notify "$(video_key_for "$CLIP")" off; exit 1; }

        if systemctl is-active --quiet "$UNIT"; then
            # Already playing (the other clip, or this one): swap the file in
            # place so the cluster never flashes up between the two clips.
            if ! mpv_loadfile "$VIDEO_FILE"; then
                echo "[cluster] mpv IPC unavailable, restarting $UNIT"
                sudo -n systemctl stop "$UNIT"
                sudo -n systemctl start "$UNIT"
            fi
        else
            sudo -n systemctl start "$UNIT"
        fi || {
            echo "[cluster] failed to start $UNIT" >&2
            notify_video_keys ""
            exit 1
        }
        echo "[cluster] $CLIP playing ($VIDEO_FILE)"
        notify_video_keys "$CLIP"
        ;;
    off)
        sudo -n systemctl stop "$UNIT"
        echo "[cluster] video stopped, cluster returning"
        notify_video_keys ""
        ;;
    *)
        echo "usage: $(basename "$0") [video1|video2] on|off" >&2
        exit 2
        ;;
esac
