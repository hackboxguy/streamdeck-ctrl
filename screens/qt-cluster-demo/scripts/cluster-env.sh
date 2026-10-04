#!/bin/bash
# Shared helpers for the qt-cluster-demo screen.
#
# The cluster reads its options once, at startup, from CLUSTER_ARGS in its
# systemd EnvironmentFile. There is no runtime control channel, so a theme or
# camera change means rewriting that line and restarting the unit -- which is
# also what makes the choice survive a reboot. A warm restart costs about
# 1.3 s on a Pi 4, so the screen goes dark briefly and comes back.

CLUSTER_HOME="${CLUSTER_HOME:-/home/pi/qt-cluster-demo}"
ENV_FILE="${CLUSTER_ENV_FILE:-$CLUSTER_HOME/systemd/qt-cluster-demo.env}"
SOCK="${STREAMDECK_SOCK:-/run/streamdeck-ctrl/notify.sock}"

# Echo the current CLUSTER_ARGS line's value, or nothing if absent.
cluster_args() {
    [ -r "$ENV_FILE" ] || return 0
    grep -m1 '^CLUSTER_ARGS=' "$ENV_FILE" | cut -d= -f2-
}

# cluster_args_without <flag>...  -- drop each "--flag=value" token.
cluster_args_without() {
    local args; args="$(cluster_args)"
    local flag
    for flag in "$@"; do
        # shellcheck disable=SC2001  # the pattern needs sed, not ${//}
        args="$(echo "$args" | sed -E "s/(^| )--${flag}=[^ ]*//g")"
    done
    echo "$args" | tr -s ' ' | sed -E 's/^ +| +$//g'
}

# write_cluster_args "<new args>" -- replace the line and restart the unit.
write_cluster_args() {
    local new="$1"
    if [ ! -w "$ENV_FILE" ] && [ ! -w "$(dirname "$ENV_FILE")" ]; then
        echo "[cluster] $ENV_FILE is not writable" >&2
        return 1
    fi
    if grep -q '^CLUSTER_ARGS=' "$ENV_FILE"; then
        # The value contains slashes, so use a separator that cannot appear.
        sed -i "s|^CLUSTER_ARGS=.*|CLUSTER_ARGS=$new|" "$ENV_FILE"
    else
        echo "CLUSTER_ARGS=$new" >> "$ENV_FILE"
    fi
    echo "[cluster] CLUSTER_ARGS=$new"

    # While a video is playing, stage the change instead of applying it.
    #
    # Restarting the cluster here would work -- Conflicts= is bidirectional, so
    # it would stop playback -- but that makes every theme key a hidden second
    # "stop video" button. Someone lining up the next theme mid-clip would kill
    # the clip to do it. Writing the env file and stopping there keeps the press
    # from being lost: the key lights immediately, and cluster-video's
    # ExecStopPost starts the cluster with these arguments the moment the
    # playing video key is pressed off. So video ends only when a video key
    # ends it.
    if systemctl is-active --quiet cluster-video.service 2>/dev/null; then
        echo "[cluster] video playing; change staged until the video key is pressed off"
        return 0
    fi

    sudo -n systemctl restart qt-cluster-demo
    notify_video_keys ""
}

# notify <id> <on|off>
notify() {
    [ -S "$SOCK" ] || return 0
    echo "{\"id\":\"$1\",\"state\":\"$2\"}" | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
}

# --- Video-1 / Video-2 keys -------------------------------------------------
#
# Both keys drive the one cluster-video.service. Which clip it plays is the
# VIDEO_FILE line of its EnvironmentFile, which is also how sync-video-state.sh
# tells afterwards which of the two keys should be lit.

MEDIA_DIR="${CLUSTER_MEDIA_DIR:-/home/pi/media/videos}"
VIDEO_ENV_FILE="${CLUSTER_VIDEO_ENV_FILE:-$CLUSTER_HOME/systemd/cluster-video.env}"
MPV_SOCK="${CLUSTER_MPV_SOCK:-/run/cluster-video/mpv.sock}"
VIDEO_CLIPS="video1 video2"

# video_file_for <clip> -- echo the clip's path; fail for an unknown clip.
video_file_for() {
    case "$1" in
        video1) echo "$MEDIA_DIR/ref-video-1920x720.mp4" ;;
        video2) echo "$MEDIA_DIR/ref-video-2-1920x720.mp4" ;;
        *) return 1 ;;
    esac
}

# video_key_for <clip> -- echo the key's notification_id.
video_key_for() {
    case "$1" in
        video1) echo "cluster.video" ;;
        video2) echo "cluster.video2" ;;
    esac
}

# Echo the clip the env file selects (video1 when unset or unrecognised,
# matching the unit's own default).
current_video_clip() {
    local file="" clip
    [ -r "$VIDEO_ENV_FILE" ] && \
        file="$(grep -m1 '^VIDEO_FILE=' "$VIDEO_ENV_FILE" | cut -d= -f2-)"
    for clip in $VIDEO_CLIPS; do
        [ "$file" = "$(video_file_for "$clip")" ] && { echo "$clip"; return; }
    done
    echo video1
}

# write_video_file <path> -- select the clip, keeping any other lines.
write_video_file() {
    local path="$1"
    if [ ! -w "$VIDEO_ENV_FILE" ] && [ ! -w "$(dirname "$VIDEO_ENV_FILE")" ]; then
        echo "[cluster] $VIDEO_ENV_FILE is not writable" >&2
        return 1
    fi
    if grep -qs '^VIDEO_FILE=' "$VIDEO_ENV_FILE"; then
        sed -i "s|^VIDEO_FILE=.*|VIDEO_FILE=$path|" "$VIDEO_ENV_FILE"
    else
        echo "VIDEO_FILE=$path" >> "$VIDEO_ENV_FILE"
    fi
}

# mpv_loadfile <path> -- swap the playing clip in place; fails if mpv's IPC
# socket is absent or mpv rejects the command.
mpv_loadfile() {
    [ -S "$MPV_SOCK" ] || return 1
    echo "{\"command\":[\"loadfile\",\"$1\",\"replace\"]}" \
        | socat -t 2 - UNIX-CONNECT:"$MPV_SOCK" 2>/dev/null \
        | grep -q '"error":"success"'
}

# notify_video_keys <clip|""> -- light that clip's key, every other one off.
notify_video_keys() {
    local clip
    for clip in $VIDEO_CLIPS; do
        if [ "$clip" = "$1" ]; then
            notify "$(video_key_for "$clip")" on
        else
            notify "$(video_key_for "$clip")" off
        fi
    done
}
