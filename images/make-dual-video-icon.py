#!/usr/bin/env python3
"""The Dual Video key's picture, in the style of the page-1 launcher keys
(Home, Slideshow, Default Ref Video): a dark navy tile with a glowing blue
border, two screens each playing (one clip per HDMI output) joined by a sync
link, and "DUAL VIDEO" below.

    python3 images/make-dual-video-icon.py screens/display-control
"""
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

SIZE = 288           # drawn at 4x the 72 px keys; the daemon scales it
DST = "dual-video.png"
FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts", "DejaVuSans-Bold.ttf")

BLUE = (40, 130, 255)
GLOW = (60, 150, 255)
WHITE = (245, 248, 255)
NAVY_TOP = (14, 26, 58)
NAVY_BOTTOM = (4, 9, 24)


def rounded(draw, box, r, **kw):
    draw.rounded_rectangle(box, radius=r, **kw)


def tile():
    img = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
    m = 14
    # vertical navy gradient inside the border
    grad = Image.new("RGB", (SIZE, SIZE))
    gd = ImageDraw.Draw(grad)
    for y in range(SIZE):
        t = y / (SIZE - 1)
        gd.line([(0, y), (SIZE, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(NAVY_TOP, NAVY_BOTTOM)))
    mask = Image.new("L", (SIZE, SIZE), 0)
    rounded(ImageDraw.Draw(mask), (m, m, SIZE - m, SIZE - m), 40, fill=255)
    img.paste(grad, (0, 0), mask)
    # glowing border: a blurred wide stroke under a crisp one
    glow = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
    rounded(ImageDraw.Draw(glow), (m, m, SIZE - m, SIZE - m), 40, outline=GLOW, width=14)
    glow = glow.filter(ImageFilter.GaussianBlur(9))
    img = ImageChops.lighter(img, glow)
    rounded(ImageDraw.Draw(img), (m, m, SIZE - m, SIZE - m), 40, outline=BLUE, width=5)
    return img


def screen(draw, x, y, w, h):
    """a monitor: rounded frame, a stand, a play triangle"""
    rounded(draw, (x, y, x + w, y + h), 10, outline=WHITE, width=7, fill=(10, 30, 80))
    cx, cy = x + w // 2, y + h // 2
    s = h * 0.24
    draw.polygon([(cx - s * 0.75, cy - s), (cx - s * 0.75, cy + s), (cx + s, cy)], fill=WHITE)
    draw.line([(cx, y + h + 3), (cx, y + h + 16)], fill=WHITE, width=7)
    draw.line([(cx - 20, y + h + 17), (cx + 20, y + h + 17)], fill=WHITE, width=7)


def main(directory):
    img = tile()
    d = ImageDraw.Draw(img)
    w, h, y = 82, 66, 66
    screen(d, 38, y, w, h)
    screen(d, SIZE - 38 - w, y, w, h)
    # sync link between the screens: a short bar with arrow heads both ways
    cy = y + h // 2
    x0, x1 = 38 + w + 7, SIZE - 38 - w - 7
    d.line([(x0 + 8, cy), (x1 - 8, cy)], fill=BLUE, width=7)
    d.polygon([(x0, cy), (x0 + 14, cy - 11), (x0 + 14, cy + 11)], fill=BLUE)
    d.polygon([(x1, cy), (x1 - 14, cy - 11), (x1 - 14, cy + 11)], fill=BLUE)
    # label
    font = ImageFont.truetype(FONT, 37)
    for text, ty in (("DUAL", 172), ("VIDEO", 212)):
        tw = d.textlength(text, font=font)
        d.text(((SIZE - tw) / 2, ty), text, font=font, fill=WHITE)
    out = os.path.join(directory, DST)
    img.save(out, optimize=True)
    print(out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
