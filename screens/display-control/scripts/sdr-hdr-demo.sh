#!/bin/bash
# SDR vs HDR10+ side-by-side demo — thin wrapper for the Stream Deck keys.
# Usage: sdr-hdr-demo.sh peru|test|stop  (see /home/pi/sdr-hdr-demo/demo-ctl.sh)
exec /home/pi/sdr-hdr-demo/demo-ctl.sh "$@"
