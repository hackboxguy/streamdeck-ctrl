#!/usr/bin/env python3
"""HDMI timing keys' pictures made from the 12.3" NQ5 key's art: its two
lines ("12.3" above the bar, "NQ5" below) replaced by another display's
name. As for the other timing keys, the art is the blue "off" state and
"on" is the same picture with green and blue swapped. The original's
typeface is not available, so the text is a bold sans scaled to the
original's line height, with a blue glow like the original's.

    python3 images/make-hdmi-timing-icon.py screens/display-control
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts", "DejaVuSans-Bold.ttf")
SRC = "12-3-nq5-raw.png"
SIZE = 72
# file stem -> (line above the bar, line below the bar)
KEYS = {"12-3-nq1v11": ("12.3", "NQ1.1"), "27": ("27", "WIDE")}
# the original's text boxes in SRC (1254 x 1254): rows and the widest columns
TOP = (350, 591)
BOTTOM = (740, 977)
X0, X1 = 220, 1030
STROKE = 14       # the original letters are heavier than DejaVu Bold
STRETCH = 1.25    # ... and wider
PAD = 40          # the glow around the letters, erased with them


def fill_columns(a, x0, y0, x1, y1):
    """Each column of the box: a straight blend from the background just
    above it to the background just below it."""
    top, bottom = a[y0 - 1, x0:x1 + 1].astype(float), a[y1 + 1, x0:x1 + 1].astype(float)
    t = np.linspace(0, 1, y1 - y0 + 1)[:, None, None]
    a[y0:y1 + 1, x0:x1 + 1] = (top[None] * (1 - t) + bottom[None] * t).astype(np.uint8)


def text_mask(text, height, max_width, size):
    """The text rendered big, scaled to the line height and widened like the
    original's squarish letters, but never wider than the original's widest
    line."""
    font = ImageFont.truetype(FONT, 400)
    box = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font, stroke_width=STROKE)
    w, h = box[2] - box[0], box[3] - box[1]
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((-box[0], -box[1]), text, font=font, fill=255,
                              stroke_width=STROKE, stroke_fill=255)
    width = min(max_width, round(w * height / h * STRETCH))
    mask = mask.resize((width, height), Image.LANCZOS)
    full = Image.new("L", size, 0)
    full.paste(mask, ((size[0] - width) // 2, 0))
    return full


def draw_line(img, text, rows):
    y0, y1 = rows
    height = y1 - y0 + 1
    mask = Image.new("L", img.size, 0)
    mask.paste(text_mask(text, height, X1 - X0, (img.size[0], height)), (0, y0))
    glow = mask.filter(ImageFilter.GaussianBlur(14))
    blue = Image.new("RGB", img.size, (0, 110, 255))
    img.paste(blue, (0, 0), glow.point(lambda v: min(255, v * 2)))
    img.paste(Image.new("RGB", img.size, (255, 255, 255)), (0, 0), mask)


def make(src_dir, stem, lines):
    a = np.array(Image.open(os.path.join(src_dir, SRC)).convert("RGB"))
    for y0, y1 in (TOP, BOTTOM):
        fill_columns(a, X0 - PAD, y0 - PAD, X1 + PAD, y1 + PAD)
    img = Image.fromarray(a)
    draw_line(img, lines[0], TOP)
    draw_line(img, lines[1], BOTTOM)
    img.save(os.path.join(src_dir, stem + "-raw.png"))
    off = img.resize((SIZE, SIZE), Image.LANCZOS)
    r, g, b = off.split()
    on = Image.merge("RGB", (r, b, g))
    off.save(os.path.join(src_dir, stem + "-off.bmp"))
    on.save(os.path.join(src_dir, stem + "-on.bmp"))


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "screens/display-control"
    for stem, lines in KEYS.items():
        make(out, stem, lines)
        print(stem, "->", lines)
