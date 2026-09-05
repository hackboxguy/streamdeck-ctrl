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
    # ExecStopPost starts the cluster with these arguments the moment the video
    # key is pressed off. So video ends only when the video key ends it.
    if systemctl is-active --quiet cluster-video.service 2>/dev/null; then
        echo "[cluster] video playing; change staged until the video key is pressed off"
        return 0
    fi

    sudo -n systemctl restart qt-cluster-demo
    notify cluster.video off
}

# notify <id> <on|off>
notify() {
    [ -S "$SOCK" ] || return 0
    echo "{\"id\":\"$1\",\"state\":\"$2\"}" | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
}
