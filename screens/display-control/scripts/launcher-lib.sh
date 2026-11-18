# launcher-lib.sh - talk to the qt-demo-launcher (sourced by the key scripts)
# shellcheck shell=bash
#
# The launcher serves one command connection at a time and closes any other
# that arrives meanwhile, before reading it ("Connection reset by peer"):
# the Stream Deck's state watches poll it every 1-3 s, and while it stops an
# app it answers nothing for up to 3 s. A reset command never ran, so each
# call here is retried.
#
#   launcher_app            the running app's id, "none", or nothing (exit 1)
#                           when the launcher does not answer
#   launcher_cmd CMD [ARG]  the launcher's answer (OK... or ERROR:...);
#                           exit 1 when it does not answer
#   launcher_stop_app       stop the running app (if any) and wait until it
#                           is gone, Kodi's kodi.bin included; exit 1 if an
#                           app still runs
#
# LAUNCHER_CLIENT overrides the client (tests).
LAUNCHER="${LAUNCHER_CLIENT:-/home/pi/micropanel/usr/bin/launcher-client}"
LAUNCHER_SRV="127.0.0.1:8081"

launcher_app() {
    local a
    for _ in 1 2 3 4 5; do
        a=$("$LAUNCHER" --srv="$LAUNCHER_SRV" --command=get-running-app 2>/dev/null | head -n 1)
        case "$a" in
            ""|*[!a-z0-9_.-]*) sleep 0.2 ;;
            *) echo "$a"; return 0 ;;
        esac
    done
    return 1
}

launcher_cmd() {
    local out
    for _ in 1 2 3 4 5; do
        out=$("$LAUNCHER" --srv="$LAUNCHER_SRV" --command="$1" ${2:+--command-arg="$2"} 2>&1)
        case "$out" in OK*|ERROR:*) echo "$out"; return 0 ;; esac
        sleep 0.3
    done
    echo "${out:-no answer}"
    return 1
}

launcher_stop_app() {
    local a end=$((SECONDS + 10))
    a=$(launcher_app)
    if [ "$a" != none ]; then          # also when unknown: stop-app is harmless with nothing running
        launcher_cmd stop-app >/dev/null || return 1
        while [ "$SECONDS" -lt "$end" ]; do
            a=$(launcher_app) && [ "$a" = none ] && break
            sleep 0.25
        done
    fi
    # /usr/bin/kodi ends as soon as it passes the launcher's SIGTERM on, so
    # the launcher reports "none" while kodi.bin still takes 2-3 s to exit and
    # keeps the display: an app started then cannot open it
    for _ in $(seq 1 50); do
        pgrep -x kodi.bin >/dev/null || break
        sleep 0.1
    done
    [ "$a" = none ]
}
