#!/usr/bin/env python3
"""The PC Source key's pictures, after the Display Power key (make-display-power-icon.py):

  pc-source-on.bmp / pc-source-off.bmp   a monitor and a USB trident over "PC SOURCE";
                                         on = blue frame and screen, "USB ON" pill;
                                         off = grey, "OFF" pill

    python3 images/make-pc-source-icons.py screens/display-control
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
font = os.path.join(HERE, "..", "fonts", "DejaVuSans-Bold.ttf")
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "screens", "display-control")
SS = 4
N = 72 * SS


def F(px): return ImageFont.truetype(font, px * SS)
def make(on):
    im = Image.new("RGB", (N, N), (0, 0, 0)); d = ImageDraw.Draw(im)
    frame = (40, 140, 255) if on else (110, 110, 110)
    bg = (12, 18, 34) if on else (26, 26, 28)
    d.rounded_rectangle([3*SS, 3*SS, N-3*SS, N-3*SS], radius=12*SS, fill=bg, outline=frame, width=3*SS)
    # PC monitor
    scr = (70, 150, 240) if on else (20, 20, 22)
    d.rounded_rectangle([16*SS, 11*SS, 46*SS, 32*SS], radius=2*SS, fill=scr, outline=(200, 205, 215), width=2*SS)
    d.rectangle([29*SS, 32*SS, 33*SS, 36*SS], fill=(200, 205, 215))
    d.rectangle([24*SS, 36*SS, 38*SS, 38*SS], fill=(200, 205, 215))
    # USB trident to the right of the monitor
    c = (90, 200, 255) if on else (140, 140, 140)
    x = 54*SS
    d.line([x, 13*SS, x, 34*SS], fill=c, width=2*SS)
    d.polygon([(x-3*SS, 16*SS), (x+3*SS, 16*SS), (x, 11*SS)], fill=c)
    d.line([x, 27*SS, x-5*SS, 23*SS, x-5*SS, 20*SS], fill=c, width=2*SS)
    d.ellipse([x-7*SS, 17*SS, x-3*SS, 21*SS], fill=c)
    d.line([x, 30*SS, x+5*SS, 26*SS, x+5*SS, 22*SS], fill=c, width=2*SS)
    d.rectangle([x+3*SS, 19*SS, x+7*SS, 23*SS], fill=c)
    d.ellipse([x-3*SS, 32*SS, x+3*SS, 38*SS], fill=c)
    t = "PC SOURCE"; f = F(8.5)
    w = d.textlength(t, font=f); d.text(((N-w)/2, 41*SS), t, font=f, fill=(235, 238, 245))
    pill = [18*SS, 53*SS, 54*SS, 63*SS]
    if on:
        d.rounded_rectangle(pill, radius=6*SS, fill=(20, 70, 170), outline=(60, 150, 255), width=1*SS)
        t = "USB ON"
    else:
        d.rounded_rectangle(pill, radius=6*SS, fill=(30, 30, 32), outline=(110, 110, 110), width=1*SS)
        t = "OFF"
    f = F(8); w = d.textlength(t, font=f); d.text(((N-w)/2, 54.2*SS), t, font=f, fill=(240, 240, 240))
    return im.resize((72, 72), Image.LANCZOS)
make(True).save(out + "/pc-source-on.bmp"); make(False).save(out + "/pc-source-off.bmp")
