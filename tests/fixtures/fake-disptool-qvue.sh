#!/bin/bash
# A stand-in for disptool --device=ioc on a 3x QVue, for the OTA-FPGA flow
# tests (tests/test_ota_fpga_flow.py). State lives in $FAKE_STATE/<name>:
#
#   version   display_manager version digits, e.g. 0110
#   link      FPGA link byte as fpgaident prints it (01, 02, 00, FF)
#   image     IDENTIFY image byte (link 01)
#   golden    1 = "the GOLDEN image is running"
#   engine    1 = the running image has the OTA engine (PPSPI page 1)
#   addr0     what flash address 0 holds: golden | vendor | other
#   slot      what the UPDATE slot holds: update | other
#   flashid   ok | ff (begin fails with FU_ERR 0x02)
#   failwrite a file basename whose write fails (the session stays open)
#   session   0 | direct | engine
#
# Every call is appended to $FAKE_STATE/calls as "<command> <value>".

S=$FAKE_STATE
get() { cat "$S/$1" 2>/dev/null; }
put() { echo "$2" > "$S/$1"; }

cmd=""; val=""
for a in "$@"; do
    case "$a" in
        --command=*) cmd=${a#*=} ;;
        --value=*)   val=${a#*=} ;;
    esac
done
echo "$cmd $val" >> "$S/calls"

boot() {   # the FPGA configures from the flash
    if [ "$(get addr0)" = golden ]; then
        put link 01; put engine 1
        if [ "$(get slot)" = update ]; then put image DC; put golden 0
        else put image D7; put golden 1; fi
    else
        put link 02; put image FF; put golden 0; put engine 0
    fi
}

case "$cmd" in
iocversion)
    v=$(get version)
    echo "FW Version : v${v:0:2}.${v:2:2}"
    echo "App Name   : display_manager"
    echo "Board Name : QVUE_9090"
    ;;
fpgaident)
    echo "FPGA link  : 0x$(get link)  x"
    if [ "$(get link)" = 01 ]; then
        echo "IDENTIFY   : 50 01 17 93 | 11 07 00 $(get image) | 00 03 00 00 | 26 13 19 43"
        if [ "$(get engine)" = 1 ]; then echo "  pages    : 0x07 = 0 1 2"; else echo "  pages    : 0x01 = 0"; fi
        [ "$(get golden)" = 1 ] && echo "  ST       : 0x04  <- the GOLDEN image is running (a fallback, or GOLDEN alone)"
    else
        echo "IDENTIFY   : FF FF FF FF | FF FF FF FF | FF FF FF FF | FF FF FF FF"
    fi
    ;;
fpgaflash)
    op=${val%%[:,]*}
    case "$op" in
    abort)
        if [ "$(get session)" = 0 ]; then echo "no session open"
        else put session 0; boot; echo "session closed (abort): PROGRAM_B released, DONE after 50 ms (0x32)"; fi ;;
    end)
        put session 0; boot
        echo "session closed (end): PROGRAM_B released, DONE after 48 ms (0x30), longest main-loop pass 900 us, 0.30 s" ;;
    begin)
        put session direct
        if [ "$(get flashid)" = ff ]; then
            echo "fpgaflash begin: flash id is not 9D 60 18 (read 0xFF 0xFF 0xFF)" >&2
            exit 1
        fi
        echo "session open: display off, PROGRAM_B low, flash id 9D 60 18" ;;
    verify)
        f=$(basename "${val#verify:}"); f=${f%%,*}
        case "$f:$(get addr0)" in
            3xqvue.bin:golden|3xqvue-legacy.bin:vendor) m=MATCH ;;
            *) m=MISMATCH ;;
        esac
        echo "verify 0x000000+1245184: flash CRC-32 0x12345678, file 0x12345678  $m" ;;
    write)
        spec=${val#write:}; f=$(basename "${spec%%,*}"); rest=${spec#*,}; addr=${rest%%,*}
        echo "erase 100 %"
        echo "program 50 %"
        if [ "$f" = "$(get failwrite)" ]; then
            echo "fpgaflash write: page program failed" >&2
            echo "the session is LEFT OPEN (display off, PROGRAM_B low)" >&2
            exit 1
        fi
        echo "program 100 %"
        echo "verify 100 %"
        if [ "$addr" = 0x0 ]; then
            case "$val" in *,golden) ;; *) echo "FU_ERR 0x0B" >&2; exit 1 ;; esac
            put addr0 golden
        else
            put slot update
        fi
        case "$val" in
            *,engine) boot; echo "engine session closed (end): display off, BOOT of 0x400000, DONE after 48 ms" ;;
        esac ;;
    *) echo "fake: unknown fpgaflash $val" >&2; exit 1 ;;
    esac ;;
*)
    echo "fake: unknown command $cmd" >&2; exit 1 ;;
esac
exit 0
