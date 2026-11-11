#!/usr/bin/env python3
"""The volume keys' pictures, after the brightness keys:

  volume-up.png / volume-down.png  round glowing buttons like brightness-up/-down
                                   (blue / amber), a speaker with an arrow
  volume-value.png                 the Volume level key's base, like
                                   brightness-value.png: a navy tile, a small
                                   speaker on top, room for the value below
  mute-on.png / mute-off.png       the Mute toggle: muted = red glow, the
                                   speaker crossed out; not muted = blue glow,
                                   the speaker with its waves; "MUTE" below

    python3 images/make-volume-icons.py screens/display-control
"""
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

SIZE = 288
FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts", "DejaVuSans-Bold.ttf")
WHITE = (245, 248, 255)
BLUE = (40, 130, 255)
AMBER = (255, 160, 20)
RED = (240, 50, 50)
NAVY_TOP, NAVY_BOTTOM = (14, 26, 58), (4, 9, 24)


def glow_outline(img, shape, color, width, blur, crisp=5):
    """a glowing outline: a blurred wide stroke lightened in, a crisp one on top"""
    g = Image.new("RGB", img.size)
    shape(ImageDraw.Draw(g), color, width)
    img = ImageChops.lighter(img, g.filter(ImageFilter.GaussianBlur(blur)))
    shape(ImageDraw.Draw(img), color, crisp)
    return img


def navy(img, shape):
    grad = Image.new("RGB", img.size)
    gd = ImageDraw.Draw(grad)
    for y in range(SIZE):
        t = y / (SIZE - 1)
        gd.line([(0, y), (SIZE, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(NAVY_TOP, NAVY_BOTTOM)))
    mask = Image.new("L", img.size, 0)
    shape(ImageDraw.Draw(mask), 255)
    img.paste(grad, (0, 0), mask)
    return img


def speaker(d, cx, cy, s, color=WHITE, waves=2, wave_color=None):
    """a speaker centred at (cx, cy), s = its height"""
    h = s / 2
    body = [(cx - h * 0.95, cy - h * 0.38), (cx - h * 0.45, cy - h * 0.38), (cx + h * 0.15, cy - h),
            (cx + h * 0.15, cy + h), (cx - h * 0.45, cy + h * 0.38), (cx - h * 0.95, cy + h * 0.38)]
    d.polygon(body, fill=color)
    w = max(4, int(s * 0.07))
    for i in range(waves):
        r = h * (0.55 + 0.38 * i)
        x0 = cx + h * 0.15
        d.arc([x0 - r, cy - r, x0 + r, cy + r], -45, 45, fill=wave_color or color, width=w)


def arrow(d, cx, cy, s, up, color):
    w = s * 0.5
    if up:
        d.polygon([(cx, cy - s / 2), (cx - w, cy), (cx + w, cy)], fill=color)
        d.rectangle([cx - w * 0.4, cy, cx + w * 0.4, cy + s / 2], fill=color)
    else:
        d.polygon([(cx, cy + s / 2), (cx - w, cy), (cx + w, cy)], fill=color)
        d.rectangle([cx - w * 0.4, cy - s / 2, cx + w * 0.4, cy], fill=color)


def round_button(up):
    color = BLUE if up else AMBER
    img = Image.new("RGB", (SIZE, SIZE))
    c, r = SIZE / 2, SIZE / 2 - 22
    circ = lambda d, col, w: d.ellipse([c - r, c - r, c + r, c + r], outline=col, width=w)
    img = navy(img, lambda d, f: d.ellipse([c - r, c - r, c + r, c + r], fill=f))
    img = glow_outline(img, circ, color, 18, 10, 7)
    d = ImageDraw.Draw(img)
    speaker(d, c - 10, c + (22 if up else -22), 112, waves=2)
    arrow(d, c, c - 72 if up else c + 72, 54, up, WHITE)
    return img


def tile(color):
    img = Image.new("RGB", (SIZE, SIZE))
    m = 14
    box = (m, m, SIZE - m, SIZE - m)
    img = navy(img, lambda d, f: d.rounded_rectangle(box, 40, fill=f))
    return glow_outline(img, lambda d, col, w: d.rounded_rectangle(box, 40, outline=col, width=w), color, 14, 9)


def label(img, text, y, size=40):
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, size)
    d.text(((SIZE - d.textlength(text, font=font)) / 2, y), text, font=font, fill=WHITE)


def main(directory):
    out = {}
    out["volume-up.png"] = round_button(True)
    out["volume-down.png"] = round_button(False)

    img = tile(BLUE)                      # the level key: the value is drawn below
    speaker(ImageDraw.Draw(img), SIZE / 2 - 8, 74, 70, waves=2)
    out["volume-value.png"] = img

    img = tile(BLUE)                      # not muted
    speaker(ImageDraw.Draw(img), SIZE / 2 - 22, 112, 120, waves=3)
    label(img, "MUTE", 200)
    out["mute-off.png"] = img

    img = tile(RED)                       # muted
    d = ImageDraw.Draw(img)
    speaker(d, SIZE / 2 - 30, 112, 120, waves=0)
    x, y, s = SIZE / 2 + 40, 112, 30
    d.line([(x - s, y - s), (x + s, y + s)], fill=RED, width=14)
    d.line([(x - s, y + s), (x + s, y - s)], fill=RED, width=14)
    label(img, "MUTE", 200)
    out["mute-on.png"] = img

    for name, im in out.items():
        path = os.path.join(directory, name)
        im.save(path, optimize=True)
        print(path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
