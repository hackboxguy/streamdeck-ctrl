#!/usr/bin/env python3
"""The 14.6" EJ FPGA flash key's picture: the 12.3" NQ5 key's picture with
its two "12-3NQ5" texts (the chip's label and the big line) replaced by
"14-6-EJ". The original's typeface is not available, so the text is a bold
sans stretched to the original's width and weight.

    python3 images/make-ej-fpga-icon.py screens/display-control
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"
SRC = "12-3-nq5-fpga-flash.png"
DST = "14-6-ej-fpga-flash.png"
TEXT = "14-6-EJ"


def fill_columns(a, x0, y0, x1, y1):
    """Each column of the box: a straight blend from the background just
    above it to the background just below it (between the chip and the
    "FPGAFlash" line the background is a smooth dark glow)."""
    top, bottom = a[y0 - 1, x0:x1 + 1].astype(float), a[y1 + 1, x0:x1 + 1].astype(float)
    t = np.linspace(0, 1, y1 - y0 + 1)[:, None, None]
    a[y0:y1 + 1, x0:x1 + 1] = (top[None] * (1 - t) + bottom[None] * t).astype(np.uint8)


def text_image(text, height, width, colour, stroke):
    """The text rendered big, then scaled to exactly height x width."""
    font = ImageFont.truetype(FONT, 400)
    box = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font, stroke_width=stroke)
    w, h = box[2] - box[0], box[3] - box[1]
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((-box[0], -box[1]), text, font=font, fill=255,
                              stroke_width=stroke, stroke_fill=255)
    mask = mask.resize((width, height), Image.LANCZOS)
    solid = Image.new("RGB", (width, height), colour)
    return solid, mask


def main(directory):
    img = Image.open(os.path.join(directory, SRC)).convert("RGB")
    a = np.asarray(img).copy()

    # the big line: x 190..1053, y 721..863 (measured from the white pixels)
    fill_columns(a, 176, 712, 1068, 874)
    # the chip's label "12-3NQ5" (x ~395..625, y ~392..444): chip texture from
    # the chip body below the "FPGA" line (no pin-1 marker there), mirrored
    # to fill the height; the "FPGA" line stays
    body = a[504:532, 380:648]
    a[386:450, 380:648] = np.concatenate([body, body[::-1], body[:8]])
    out = Image.fromarray(a)

    text, mask = text_image(TEXT, 142, 864, (255, 255, 255), 14)
    out.paste(text, (190, 721), mask)
    label, mask = text_image(TEXT, 44, 214, (226, 226, 226), 6)
    out.paste(label, (404, 396), mask)

    out.save(os.path.join(directory, DST))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
