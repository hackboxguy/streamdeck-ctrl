#!/bin/bash
# Home key: stop whatever plays, then return qt-demo-launcher to its home screen.
#
# 1. player-ctl.sh stop-all stops every active player, including ones the
#    launcher did not start (the SDR/HDR shoot-out's sync unit, which would
#    otherwise keep driving Kodi and the Zidoo; a dual-video-player started by
#    hand or by a measurement script).
# 2. The launcher's stop-app ends its running app (Kodi, USB Media, ...), which
#    brings back the home screen. Nothing to do when no app runs.
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
LAUNCHER="/home/pi/micropanel/usr/bin/launcher-client"
SRV="127.0.0.1:8081"

"$DIR/player-ctl.sh" stop-all

RUNNING=$("$LAUNCHER" --srv="$SRV" --command=get-running-app 2>/dev/null)
[ "$RUNNING" = "none" ] && exit 0

"$LAUNCHER" --srv="$SRV" --command=stop-app
