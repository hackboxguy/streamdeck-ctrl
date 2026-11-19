#!/bin/sh
# QVue warp keys (3x QVue): the realtime warp of the HDMI output done by
# br-wrapper's qvue-warpd, driven through its client qvue-warpctl.
#
#   qvue-warp.sh warp on|off        Warp key ({state} = the requested state)
#   qvue-warp.sh mirror-x on|off    Mirror H key: picture mirrored left-right (whole canvas)
#   qvue-warp.sh mirror-y on|off    Mirror V key: picture mirrored top-bottom
#   qvue-warp.sh tune on|off        Warp Tune key: tuning overlay on the panel
#   qvue-warp.sh grid on|off        Warp Grid key: built-in straight test grid as the picture
#   qvue-warp.sh step5 on|off       Warp Step 5 key: nudge step 5 px (on) or 1 px (off)
#   qvue-warp.sh panel              Warp Panel key: select the next panel
#   qvue-warp.sh handle             Warp Handle key: select the next handle
#                                   (tl t tr l c r bl b br, then panel, all)
#   qvue-warp.sh up|down|left|right move the selection by one step
#   qvue-warp.sh save --id=ID       Warp Save task key: reports success/failure to ID
#   qvue-warp.sh revert|reset       back to the saved trim / zero trim (not saved)
#   qvue-warp.sh panel-value        live value of the Warp Panel key, e.g. "P2"
#   qvue-warp.sh handle-value       live value of the Warp Handle key, e.g. "tl"
#   qvue-warp.sh grid-state         "on"/"off" for the Warp Grid key's state_watch
#   qvue-warp.sh step-state         "5"/"1" ... for the Warp Step 5 key's state_watch
#
# The daemon's /run/qvue-warp/state.json is the source of truth: the Warp,
# Warp Tune and Mirror keys watch it directly (json_key enabled / tune /
# mirror_x / mirror_y), the others
# through the *-state / *-value commands. qvue-warpd saves the warp setting
# and the mirror itself (/data/qvue-warp/warp.conf); "save" stores the trim
# (trim.json).
SOCK="${NOTIFY_SOCK:-/run/streamdeck-ctrl/notify.sock}"
STATE_JSON="${QVUE_WARP_STATE:-/run/qvue-warp/state.json}"

CTL=""
for c in "${QVUE_WARPCTL:-}" /home/pi/micropanel/bin/qvue-warpctl /usr/bin/qvue-warpctl; do
    [ -n "$c" ] && [ -x "$c" ] && CTL="$c" && break
done
[ -n "$CTL" ] || CTL=$(command -v qvue-warpctl 2>/dev/null)

notify() {   # notify ID state|value VALUE
    [ -S "$SOCK" ] || return 0
    echo "{\"id\":\"$1\",\"$2\":\"$3\"}" | socat -t 1 - UNIX-CONNECT:"$SOCK" >/dev/null 2>&1 || true
}

ctl() {
    if [ -z "$CTL" ]; then
        echo "qvue-warp: qvue-warpctl not found" >&2
        return 2
    fi
    out=$(timeout 15 "$CTL" "$@" 2>&1)
    rc=$?
    echo "qvue-warp: $* -> $out"
    [ $rc -eq 0 ]
}

# a string field of state.json ("panel": 2 or "handle": "tl")
field() {
    [ -r "$STATE_JSON" ] || return 1
    sed -n "s/.*\"$1\": *\"\{0,1\}\([^\",}]*\)\"\{0,1\}.*/\1/p" "$STATE_JSON" | head -n 1
}

# a toggle press: run the command, put the icon back if it failed
toggle() {   # toggle ID STATE COMMAND...
    id=$1 state=$2
    shift 2
    if ! ctl "$@"; then
        notify "$id" state "$([ "$state" = on ] && echo off || echo on)"
        exit 1
    fi
    notify "$id" state "$state"
}

onoff() {
    case "${1:-}" in
        on|off) ;;
        *) echo "qvue-warp: expected on or off" >&2; exit 2 ;;
    esac
}

case "${1:-}" in
    warp)   onoff "${2:-}"; toggle display.qvue_warp "$2" "$2" ;;
    mirror-x) onoff "${2:-}"; toggle display.qvue_warp_mirror_x "$2" mirror x "$2" ;;
    mirror-y) onoff "${2:-}"; toggle display.qvue_warp_mirror_y "$2" mirror y "$2" ;;
    tune)   onoff "${2:-}"; toggle display.qvue_warp_tune "$2" tune "$2" ;;
    grid)
        onoff "${2:-}"
        [ "$2" = on ] && src=grid || src=fb0
        toggle display.qvue_warp_grid "$2" tune source "$src"
        ;;
    step5)
        onoff "${2:-}"
        [ "$2" = on ] && n=5 || n=1
        toggle display.qvue_warp_step5 "$2" step "$n"
        ;;
    panel)
        ctl select panel next || exit 1
        notify display.qvue_warp_panel value "P$(field panel)"
        ;;
    handle)
        ctl select next || exit 1
        notify display.qvue_warp_handle value "$(field handle)"
        ;;
    up)    ctl nudge 0 -1 ;;
    down)  ctl nudge 0 1 ;;
    left)  ctl nudge -1 0 ;;
    right) ctl nudge 1 0 ;;
    save)
        id=$(echo "${2:-}" | sed -n 's/^--id=//p')
        [ -n "$id" ] && notify "$id" state running
        if ctl save; then
            [ -n "$id" ] && notify "$id" state success
        else
            [ -n "$id" ] && notify "$id" state failure
            exit 1
        fi
        ;;
    revert) ctl revert ;;
    reset)  ctl reset ;;
    panel-value)
        p=$(field panel) && [ -n "$p" ] && echo "P$p" || echo "--"
        ;;
    handle-value)
        h=$(field handle) && [ -n "$h" ] && echo "$h" || echo "--"
        ;;
    grid-state)
        s=$(field source) || exit 1
        [ "$s" = grid ] && echo on || echo off
        ;;
    step-state)
        s=$(field step) || exit 1
        echo "${s:-1}"
        ;;
    *)
        echo "usage: qvue-warp.sh warp|mirror-x|mirror-y|tune|grid|step5 on|off | panel | handle | up|down|left|right |" >&2
        echo "       save --id=ID | revert | reset | panel-value | handle-value | grid-state | step-state" >&2
        exit 2
        ;;
esac
