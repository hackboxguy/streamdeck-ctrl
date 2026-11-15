#!/bin/bash
# A fake disptool for flash-fpga-ab.sh, next to fake-ofl-xc7s50.sh. What the FPGA
# runs follows from $FAKE_STATE/flash after a display power cycle (or an ofl
# reset): our GOLDEN at 0 -> it jumps to the slot: the UPDATE answers
# (10 18 00 88, OTA) when the slot holds it, else GOLDEN (09 28 00 50); anything
# else at 0 -> the vendor image, which has no 0x1E interface.
#   ioc      "ok" or "none" (the display IOC does not answer)
#   iocrails "0": its power cycle does not restart the FPGA (rails not switched)
#   golden / update   paths of the images (written by the test)
S=$FAKE_STATE
echo "disptool $*" >> "$S/calls"
st() { cat "$S/$1" 2>/dev/null; }
dev="" cmd="" val=""
for a in "$@"; do
    case "$a" in
        --device=*) dev=${a#*=} ;; --command=*) cmd=${a#*=} ;; --value=*) val=${a#*=} ;;
    esac
done

running() {   # GOLDEN | OTA | vendor | bridge
    [ "$(st fpga)" = bridge ] && { echo bridge; return; }
    [ "$(st power)" = off ] && { echo off; return; }
    python3 -I - "$S/flash" "$(st golden)" "$(st update)" <<'EOF'
import sys
f = open(sys.argv[1], "rb").read()
g, u = open(sys.argv[2], "rb").read(), open(sys.argv[3], "rb").read()
if f[:len(g)] != g:
    print("vendor")
elif f[0x400000:0x400000 + len(u)] == u:
    print("OTA")
else:
    print("GOLDEN")
EOF
}

case "$dev:$cmd" in
    ioc:disppower)
        [ "$(st ioc)" = ok ] || { echo "no answer"; exit 1; }
        case "$val" in
            off) echo off > "$S/power"; echo "Display power set to OFF" ;;
            on)  echo on > "$S/power"; [ "$(st iocrails)" = 0 ] || echo image > "$S/fpga"
                 echo "Display power set to ON" ;;
            *)   echo "Display Power: ON" ;;
        esac ;;
    fpganew:version)
        case "$(running)" in
            OTA)    echo "Raw Bytes   : 0x10 0x18 0x00 0x88" ;;
            GOLDEN) echo "Raw Bytes   : 0x09 0x28 0x00 0x50" ;;
            *)      echo "Failed to read version"; exit 1 ;;
        esac ;;
    fpganew:activbitstream)
        r=$(running)
        case "$r" in OTA|GOLDEN) echo "$r" ;; *) echo "no answer"; exit 1 ;; esac ;;
    *) echo "fake disptool: $dev $cmd" >&2; exit 1 ;;
esac
