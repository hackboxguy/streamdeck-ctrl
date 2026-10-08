#!/bin/bash
# Cluster Demo: the modern cluster (Cluster Demo V2) in its analog theme, the
# "Legacy" look - full dials over the map, the DMS panel (camera, driver
# vitals) off. The old cluster-demo app is no longer started (its launcher
# tile is disabled).
#
# The DMS panel and the map are the cluster's remembered switches in
# /data/cluster, shared with page 3's DMS and Map keys and the cluster's own
# buttons: this key sets them (DMS off, map on) and they stay so for the next
# themes until switched back. Without a writable /data/cluster (not the A/B
# image) the cluster starts with its defaults.
DIR="$(cd "$(dirname "$0")" && pwd)"

"$DIR/cluster-state.sh" dms off
"$DIR/cluster-state.sh" map on
exec "$DIR/cluster-theme.sh" analog
