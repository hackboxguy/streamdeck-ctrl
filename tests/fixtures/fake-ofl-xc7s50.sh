#!/bin/bash
# A fake openFPGALoader for flash-fpga-ab.sh: one XC7S50 with an IS25LP128 whose
# 16 MiB is the file $FAKE_STATE/flash. State files in $FAKE_STATE:
#   jtag     "ok" (IDCODE 0x362f093) or "none" (empty chain)
#   jedec    the JEDEC ID the bridge reads (0x9d6018)
#   failwrite  N > 0: a write fails after its first N bytes
#   fpga     what the FPGA holds: "image" (configured from flash) or "bridge"
# Every call is appended to $FAKE_STATE/calls as "ofl <args>".
S=$FAKE_STATE
echo "ofl $*" >> "$S/calls"
st() { cat "$S/$1" 2>/dev/null; }

detect=0 file="" dump="" size="" off=0 verify=0 skipreset=0 reset=0 bridge=""
while [ $# -gt 0 ]; do
    case "$1" in
        -c) shift ;;
        -B) bridge=$2; shift ;;
        --detect) detect=1 ;;
        -f) if [ -n "${2:-}" ] && [ "${2#-}" = "$2" ]; then file=$2; shift; fi ;;
        --file-type) shift ;;
        --dump-flash) dump=$2; shift ;;
        --file-size) size=$2; shift ;;
        -o) off=$(( $2 )); shift ;;
        --verify) verify=1 ;;
        --skip-reset) skipreset=1 ;;
        -r|--reset) reset=1 ;;
        -v|--verbose) ;;
        *) echo "fake ofl: unknown $1" >&2; exit 9 ;;
    esac
    shift
done

[ "$(st jtag)" = ok ] || { echo "found 0 devices"; exit 1; }

if [ "$reset" = 1 ] && [ -z "$file" ] && [ -z "$dump" ]; then
    echo image > "$S/fpga"; echo "reset done"; exit 0
fi
if [ "$detect" = 1 ] && [ -z "$bridge" ]; then
    printf 'found 1 devices\nindex 0:\n\tidcode 0x362f093\n\tmanufacturer xilinx\n\tmodel  xc7s50\n'
    exit 0
fi
[ -n "$bridge" ] || { echo "fake ofl: flash access needs -B" >&2; exit 9; }
echo bridge > "$S/fpga"
echo "Load SRAM: [====] 100.00%"
echo "JEDEC ID: $(st jedec)"
[ "$(st jedec)" = 0x9d6018 ] || { echo "unknown flash"; exit 1; }
echo "Detected: ISSI IS25LP128 256 sectors size: 128Mb"

if [ -n "$dump" ]; then
    dd if="$S/flash" of="$dump" bs=4096 iflag=count_bytes,skip_bytes skip="$off" count="$size" status=none
    echo "Read flash : [====] 100.00%"; echo Done
elif [ -n "$file" ]; then
    cut=$(st failwrite); cut=${cut:-0}
    if [ "$cut" -gt 0 ]; then
        dd if="$file" of="$S/flash" bs=4096 iflag=count_bytes oflag=seek_bytes seek="$off" \
            count="$cut" conv=notrunc status=none
        echo "Writing: [==  ] 50.00%"; echo "write error"; exit 1
    fi
    dd if="$file" of="$S/flash" bs=4096 oflag=seek_bytes seek="$off" conv=notrunc status=none
    echo "Writing: [====] 100.00%"; echo Done
    [ "$verify" = 1 ] && echo "Verifying write (May take time)" && echo Done
fi
if [ "$skipreset" = 1 ]; then echo "Skip resetting device"; elif [ -n "$file" ]; then echo image > "$S/fpga"; fi
exit 0
