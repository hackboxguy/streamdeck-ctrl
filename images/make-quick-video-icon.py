#!/usr/bin/env python3
"""The Quick Video key's picture, in the style of Dual Video
(make-dual-video-icon.py): a dark navy tile with a glowing blue border, one
screen playing with a lightning bolt beside it (fast start), and "QUICK VIDEO"
below.

    python3 images/make-quick-video-icon.py screens/display-control
"""
import importlib.util
import os
import sys

from PIL import ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("dual_icon", os.path.join(HERE, "make-dual-video-icon.py"))
dv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dv)

DST = "quick-video.png"
AMBER = (255, 190, 40)


def main(directory):
    img = dv.tile()
    d = ImageDraw.Draw(img)
    w, h, y = 128, 92, 54
    x = 44
    dv.screen(d, x, y, w, h)
    # lightning bolt right of the screen
    bx, by = x + w + 22, y - 4
    d.polygon([(bx + 30, by), (bx + 2, by + 58), (bx + 22, by + 58), (bx + 10, by + 110),
               (bx + 48, by + 44), (bx + 27, by + 44), (bx + 44, by)], fill=AMBER)
    font = ImageFont.truetype(dv.FONT, 38)
    for text, ty in (("QUICK", 182), ("VIDEO", 222)):
        tw = d.textlength(text, font=font)
        d.text(((dv.SIZE - tw) / 2, ty), text, font=font, fill=dv.WHITE)
    path = os.path.join(directory, DST)
    img.save(path, optimize=True)
    print(path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
