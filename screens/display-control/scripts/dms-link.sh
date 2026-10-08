#!/bin/bash
# DMS Link: eth0 becomes the DHCP server of the link to the FocusDrive Xavier
# (192.168.10.1/24; the Xavier keeps its fixed 192.168.10.2), as the Network
# app's Wired card does - through br-wrapper's net-ctl.sh, so the profile is a
# NetworkManager keyfile on /data: it survives power cycles and updates, and
# a factory reset makes eth0 a DHCP client again (press the key again).
#
#   dms-link.sh          set it up (a task key: blinking while it works, then
#                        green or red; the reason is in the journal)
#   dms-link.sh --state  one word for the key's light (state_watch):
#                        serving | waiting (no cable yet) | stopped (the DHCP
#                        guard found another server) | other. A port that
#                        serves from a profile NetworkManager does not start
#                        by itself (autoconnect off) is "other": it would be
#                        a DHCP client again after the next power cycle
#
# Pressing it again is harmless: a port that already serves is left alone.
# The SOME/IP multicast route and the advertise address are cluster-v2.sh's
# business at every cluster start; this key does not touch them.
NET_CTL="${NET_CTL:-/home/pi/micropanel/bin/net-ctl.sh}"
SOCK="${STREAMDECK_SOCKET:-/run/streamdeck-ctrl/notify.sock}"
NOTIFY_ID="cluster.dms_link"
IFACE="${DMS_LINK_IFACE:-eth0}"
ADDR="${DMS_LINK_ADDR:-192.168.10.1}"
PREFIX=24
WAIT_S="${DMS_LINK_WAIT_S:-40}"     # the guard's check takes up to 30 s

# key=value of the port's status line (percent-encoded values are plain here)
port_line() { "$NET_CTL" status --iface="$IFACE" 2>/dev/null | grep -m1 "^RESULT kind=iface"; }
field() { printf '%s\n' "$1" | tr ' ' '\n' | sed -n "s/^$2=//p" | head -n 1; }

state_of() { # <status line> -> serving | waiting | stopped | checking | other
    [ "$(field "$1" guard)" = stopped ] && { echo stopped; return; }
    uuid=$(field "$1" profileuuid)
    if [ "$(field "$1" mode)" = server ] && [ "$(field "$1" cfgip)" = "$ADDR" ] \
            && [ "$(field "$1" cfgprefix)" = "$PREFIX" ] \
            && [ "$(nmcli -g connection.autoconnect connection show uuid "$uuid" 2>/dev/null)" = yes ]; then
        [ "$(field "$1" guard)" = checking ] && { echo checking; return; }
        [ "$(field "$1" carrier)" = 1 ] || { echo waiting; return; }
        [ "$(field "$1" ip)" = "$ADDR" ] && { echo serving; return; }
        # coming up (NetworkManager activating the port): give it time;
        # a port that just sits disconnected is not set up (a press fixes it)
        case $(field "$1" state) in
            connecting*|prepare|config|ip-config|ip-check|secondaries|need-auth) echo checking; return ;;
        esac
        echo other; return
    fi
    echo other
}

if [ "${1:-}" = --state ]; then
    state_of "$(port_line)"
    exit 0
fi

notify() {
    [ -S "$SOCK" ] || return 0
    printf '{"id":"%s","state":"%s"}\n' "$NOTIFY_ID" "$1" \
        | socat - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1 || true
}
finish() { # <success|failure> <reason>
    echo "dms-link: $2"
    logger -t dms-link "$2" 2>/dev/null
    notify "$1"
    [ "$1" = success ]; exit $?
}

[ -x "$NET_CTL" ] || finish failure "net-ctl.sh not found ($NET_CTL)"
line=$(port_line)
[ -n "$line" ] || finish failure "no port $IFACE here"
case $(state_of "$line") in
    serving) finish success "$IFACE already serves $ADDR/$PREFIX: nothing to do" ;;
    waiting) finish success "$IFACE is set to serve $ADDR/$PREFIX: serving when a cable is connected" ;;
esac

out=$(sudo -n "$NET_CTL" wired-set --iface="$IFACE" --mode=server --ip="$ADDR" --prefix="$PREFIX" 2>&1)
rc=$?
result=$(printf '%s\n' "$out" | grep -m1 "^RESULT kind=wired")
echo "dms-link: wired-set rc=$rc $result"

# The guard probes the port before it serves; wait for its verdict
for _ in $(seq 1 "$WAIT_S"); do
    state=$(state_of "$(port_line)")
    case $state in
        serving) finish success "$IFACE serves $ADDR/$PREFIX (the Xavier at .2 gets its link)" ;;
        waiting) finish success "$IFACE is set to serve $ADDR/$PREFIX: serving when a cable is connected" ;;
        stopped) finish failure "another DHCP server on $IFACE: the guard took the port down (not the Xavier's direct cable?)" ;;
    esac
    sleep 1
done
reason=$(field "$result" reason)
finish failure "$IFACE does not serve $ADDR/$PREFIX (wired-set rc=$rc${reason:+, reason=$reason})"
