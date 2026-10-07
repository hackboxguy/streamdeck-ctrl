#!/bin/bash
# The Cluster Demo V2 switches the deck shares with the cluster's own buttons:
# its state files in /data/cluster, which a running cluster follows at once
# and cluster-v2.sh passes to the next start (the A/B image; a single-slot
# image has no /data/cluster, and the keys only say so).
#   map    on|off   map-backdrop.state
#   camera on|off   dms-video-view.state: on <-> off (the camera box); does
#                   nothing while the DMS panel is off (none)
#   dms    on|off   dms-video-view.state: off = none (no DMS panel in the
#                   middle); on = the camera key's last choice (default on)
# $2 is the key's new state ({state}). The keys light from the files
# (state_watch); a refused press is pushed back over the notify socket.
DATA_DIR="${CLUSTER_DATA_DIR:-/data/cluster}"
SOCK="${STREAMDECK_SOCKET:-/run/streamdeck-ctrl/notify.sock}"
DMS="$DATA_DIR/dms-video-view.state"
LAST="$DATA_DIR/dms-video-view.last"     # the camera choice while DMS is off

what=${1:-} state=${2:-}
case "$state" in on|off) ;; *) echo "cluster-state: expected on or off" >&2; exit 2 ;; esac

notify() { # <id> <state>
    [ -S "$SOCK" ] || return 0
    printf '{"id":"%s","state":"%s"}\n' "$1" "$2" | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1 || true
}
refuse() { # <id> <state to show> <why>
    echo "cluster-state: $3" >&2
    notify "$1" "$2"
    exit 1
}
# Whole file or nothing, owned like the directory (the cluster, as pi,
# replaces it too)
put() { # <file> <word>
    tmp=$(mktemp "$1.XXXXXX") || return 1
    if printf '%s\n' "$2" > "$tmp" && chmod 0644 "$tmp" \
            && { [ "$(id -u)" != 0 ] || chown --reference="$DATA_DIR" "$tmp"; } \
            && mv -f "$tmp" "$1"; then
        return 0
    fi
    rm -f "$tmp"
    return 1
}
word() { head -c 4 "$1" 2>/dev/null | tr -d '[:space:]'; }

case "$what" in
    map) id=cluster.map ;;
    camera) id=cluster.camera ;;
    dms) id=cluster.dms ;;
    *) echo "cluster-state: expected map, camera or dms" >&2; exit 2 ;;
esac
other=$([ "$state" = on ] && echo off || echo on)
[ -d "$DATA_DIR" ] && [ -w "$DATA_DIR" ] || refuse "$id" "$other" "no writable $DATA_DIR (not the A/B image)"

case "$what" in
    map)
        put "$DATA_DIR/map-backdrop.state" "$state" || refuse "$id" "$other" "could not write the map state" ;;
    camera)
        [ "$(word "$DMS")" = none ] && refuse "$id" off "the DMS panel is off: no camera box to switch"
        put "$DMS" "$state" || refuse "$id" "$other" "could not write the DMS state" ;;
    dms)
        current=$(word "$DMS"); [ -n "$current" ] || current=on
        if [ "$state" = off ]; then
            [ "$current" = none ] || put "$LAST" "$current"
            put "$DMS" none || refuse "$id" on "could not write the DMS state"
        else
            last=$(word "$LAST"); case "$last" in on|off) ;; *) last=on ;; esac
            [ "$current" = none ] && { put "$DMS" "$last" || refuse "$id" off "could not write the DMS state"; }
        fi ;;
esac
echo "cluster-state: $what $state"
