#!/bin/bash
# A fake xc3sprog (cable xpc2) for flash-fpga-ab.sh, over the same state as
# fake-ofl-xc7s50.sh: one XC7S50 with an IS25LP128 whose 16 MiB is the file
# $FAKE_STATE/flash. Extra state:
#   xpcfw   "loaded" or "none" (the cable's FX2 has no firmware: every call fails
#           the way the real cable does, "pcu_request_28 failed"); fake fxload
#           sets it to "loaded"
# Filespecs: <file>:R:0:BIN:<len> (read) and <file>:W:<off>:BIN (write + verify).
# Every call is appended to $FAKE_STATE/calls as "xc3 <args>".
S=$FAKE_STATE
echo "xc3 $*" >> "$S/calls"
st() { cat "$S/$1" 2>/dev/null; }

bscan="" detect=0 reconf=0 spec=""
while [ $# -gt 0 ]; do
    case "$1" in
        -c) shift ;;
        -I*) bscan=${1#-I} ;;
        -j) detect=1 ;;
        -R) reconf=1 ;;
        -p) shift ;;
        -*) echo "fake xc3sprog: unknown $1" >&2; exit 9 ;;
        *) spec=$1 ;;
    esac
    shift
done

# the real banner, word for word: it contains "failure" on every call
cat <<'BANNER'
XC3SPROG (c) 2004-2011 xc3sprog project $Rev: 774 $ OS: Linux
Free software: If you contribute nothing, expect nothing!
Feedback on success/failure/enhancement requests:
	http://sourceforge.net/mail/?group_id=170565 
Check Sourceforge for updates:
	http://sourceforge.net/projects/xc3sprog/develop

BANNER
if [ "$(st xpcfw)" != loaded ]; then
    echo "usb_control_msg(0x28 11) error sending control message: Connection timed out"
    echo "pcu_request_28 failed"
    echo "usage:	xc3sprog -c cable [options] <file0spec> <file1spec> ..."
    exit 0                       # the real one exits 0 here too
fi
[ "$(st jtag)" = ok ] || { echo "No JTAG Chain found"; exit 1; }
if [ "$reconf" = 1 ]; then echo "Device does not support reconfiguration."; exit 0; fi
if [ "$detect" = 1 ] || [ -z "$bscan" ]; then
    echo "JTAG loc.:   0  IDCODE: 0x0362f093  Desc:                         XC7S50 Rev: A  IR length:  6"
    exit 0
fi
[ -r "$bscan" ] || { echo "Can't open bscan file $bscan"; exit 1; }
echo bridge > "$S/fpga"
case "$(st jedec)" in
    0x9d6018) echo "JEDEC: 9d 60 0x18 0x9d"; echo "Found ISSI IS25LP128 Device (ID 0x6018)"
              echo "256 bytes/page, 65536 pages = 16777216 bytes total" ;;
    *)        echo "JEDEC: c2 20 0x18 0x00"; echo "Unknown JEDEC manufacturer: 0xc2 while reading"; exit 1 ;;
esac
[ -n "$spec" ] || exit 0

IFS=: read -r file act off style len <<< "$spec"
off=$(( off ))
case "$act" in
    R)  dd if="$S/flash" of="$file" bs=4096 iflag=count_bytes,skip_bytes skip="$off" count="$len" status=none ;;
    W)  cut=$(st failwrite); cut=${cut:-0}
        if [ "$cut" -gt 0 ]; then
            dd if="$file" of="$S/flash" bs=4096 iflag=count_bytes oflag=seek_bytes seek="$off" \
                count="$cut" conv=notrunc status=none
            echo "Erasing sector ..."; echo "Programming failed"; exit 0
        fi
        dd if="$file" of="$S/flash" bs=4096 oflag=seek_bytes seek="$off" conv=notrunc status=none
        echo "Verify: Success!" ;;
    *)  echo "fake xc3sprog: action $act not modelled" >&2; exit 9 ;;
esac
exit 0
