#!/bin/bash
# The SDR vs HDR10+ shoot-out (sdr-hdr-shootout-demo, /home/pi/sdr-hdr-demo):
# while its sync unit runs, it owns Kodi and the Zidoo; its demo-ctl.sh does a
# synchronized freeze and a synchronized 10 s seek (signals to sync-play.py).
# Its pause is a toggle and the sync reports the frozen state on the Player
# Pause key itself, so status is "unknown" (the key keeps what the sync said).
DEMO="${SDR_HDR_DEMO:-/home/pi/sdr-hdr-demo}/demo-ctl.sh"
UNIT=sdr-hdr-sync
case "${1:-}" in
    active)  [ -x "$DEMO" ] && systemctl is-active --quiet "$UNIT" ;;
    status)  echo unknown ;;
    pause|resume|toggle) "$DEMO" pause ;;
    seek)    case "${2:-}" in -*) "$DEMO" rew ;; *) "$DEMO" fwd ;; esac ;;   # 10 s steps
    stop)    "$DEMO" stop ;;
    *)       exit 2 ;;
esac
