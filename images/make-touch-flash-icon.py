#!/usr/bin/env python3
"""The OLED-IB Touch-Flash key's picture made from the OLED-OTS IOC-Flash
key's picture: the chip's label "OLED-OTS" becomes "OLED-IB", and the two big
lines "OLED-OTS" / "IOC-Flash" become "OLED-IB" / "Touch-Flash". As in
make-fpga-flash-icon.py, the original's typeface is not available, so the
text is a bold sans scaled to the original's height, and no wider than the
original line.

    python3 images/make-touch-flash-icon.py screens/display-control
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"
SRC = "oled-ots-ioc-flash.png"
DST = "oled-ib-touch-flash.png"
CHIP_LABEL = "OLED-IB"
# (text, box the original line's white pixels fill: x0, y0, x1, y1)
LINES = [("OLED-IB", (177, 723, 1075, 835)),
         ("Touch-Flash", (185, 877, 1071, 1007))]
# how much wider than DejaVu's own proportions the text may be stretched
# (the original's typeface is a wide one)
MAX_STRETCH = 1.3


def fill_columns(a, x0, y0, x1, y1):
    """Each column of the box: a straight blend from the background just
    above it to the background just below it."""
    top, bottom = a[y0 - 1, x0:x1 + 1].astype(float), a[y1 + 1, x0:x1 + 1].astype(float)
    t = np.linspace(0, 1, y1 - y0 + 1)[:, None, None]
    a[y0:y1 + 1, x0:x1 + 1] = (top[None] * (1 - t) + bottom[None] * t).astype(np.uint8)


def text_image(text, height, max_width, colour, stroke):
    """The text rendered big, then scaled to exactly `height`, and to its own
    proportions stretched by up to MAX_STRETCH but never past max_width."""
    font = ImageFont.truetype(FONT, 400)
    box = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font, stroke_width=stroke)
    w, h = box[2] - box[0], box[3] - box[1]
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((-box[0], -box[1]), text, font=font, fill=255,
                              stroke_width=stroke, stroke_fill=255)
    width = min(max_width, round(w * height / h * MAX_STRETCH))
    mask = mask.resize((width, height), Image.LANCZOS)
    solid = Image.new("RGB", (width, height), colour)
    return solid, mask


def main(directory):
    img = Image.open(os.path.join(directory, SRC)).convert("RGB")
    a = np.asarray(img).copy()

    # the two big lines, as one box so the glow between them blends too
    fill_columns(a, 165, 712, 1087, 1018)
    # the chip's label (x 382..635, y 409..457): chip texture from the chip
    # body below it, mirrored to fill the height
    body = a[470:500, 376:642]
    a[402:464, 376:642] = np.concatenate([body, body[::-1], body[:2]])
    out = Image.fromarray(a)

    for text, (x0, y0, x1, y1) in LINES:
        solid, mask = text_image(text, y1 - y0 + 1, x1 - x0 + 1, (255, 255, 255), 14)
        out.paste(solid, ((x0 + x1 + 1 - solid.width) // 2, y0), mask)
    solid, mask = text_image(CHIP_LABEL, 49, 254, (226, 226, 226), 6)
    out.paste(solid, ((382 + 636 - solid.width) // 2, 409), mask)

    out.save(os.path.join(directory, DST))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
