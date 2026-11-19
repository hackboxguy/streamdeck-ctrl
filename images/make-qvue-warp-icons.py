#!/usr/bin/env python3
"""The QVue warp keys' pictures (scripts/qvue-warp.sh), in the style of the
Display Power key: a dark rounded tile, a picture, a label and, for the
toggles, an ON/OFF pill. The picture is a bent grid (the pre-distortion the
warp applies) or an arrow. Drawn at 4x and scaled down to 72x72.

    python3 images/make-qvue-warp-icons.py screens/display-control
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont

FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts", "DejaVuSans-Bold.ttf")
SIZE = 72
S = 4
W = SIZE * S
BLUE = (40, 140, 255)
GREY = (110, 110, 120)
AMBER = (255, 170, 30)


def font(px):
    return ImageFont.truetype(FONT, px * S)


def centred(d, y, text, f, fill):
    box = d.textbbox((0, 0), text, font=f)
    d.text(((W - (box[2] - box[0])) // 2 - box[0], y), text, font=f, fill=fill)


def tile(lit, colour=BLUE):
    img = Image.new("RGB", (W, W), (0, 0, 0))
    d = ImageDraw.Draw(img)
    frame = colour if lit else GREY
    d.rounded_rectangle((2 * S, 2 * S, W - 2 * S, W - 2 * S), radius=9 * S,
                        fill=(10, 14, 28) if lit else (16, 16, 18), outline=frame, width=2 * S)
    return img, d, frame


def bent_grid(d, colour, box=(14, 9, 58, 35), straight=False):
    """a 5x3 grid bowed like the warp's 'smile'"""
    x0, y0, x1, y1 = [v * S for v in box]
    def pt(u, v):
        bow = 0 if straight else 5 * S * (1 - (2 * u - 1) ** 2) * (0.6 + 0.4 * v)
        return x0 + u * (x1 - x0), y0 + v * (y1 - y0) - bow + (0 if straight else 4 * S)
    for j in range(3):
        d.line([pt(i / 20, j / 2) for i in range(21)], fill=colour, width=S + S // 2)
    for i in range(5):
        d.line([pt(i / 4, j / 10) for j in range(11)], fill=colour, width=S + S // 2)


def pill(d, on, frame, text_on="ON", text_off="OFF"):
    px0, py0, px1, py1 = 18 * S, 54 * S, 54 * S, 66 * S
    d.rounded_rectangle((px0, py0, px1, py1), radius=6 * S,
                        fill=(20, 60, 140) if on else (40, 40, 44), outline=frame, width=S)
    centred(d, py0 + 2 * S, text_on if on else text_off, font(8), (255, 255, 255))


def toggle(label, on, picture, colour=BLUE, text_on="ON", text_off="OFF"):
    img, d, frame = tile(on, colour)
    picture(d, (230, 235, 245) if on else (120, 120, 130))
    centred(d, 41 * S, label, font(9), (235, 235, 240))
    pill(d, on, frame, text_on, text_off)
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def static(label, picture, colour=BLUE, label_y=46):
    img, d, _ = tile(True, colour)
    picture(d, (230, 235, 245))
    centred(d, label_y * S, label, font(10), (235, 235, 240))
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def arrow(direction):
    def draw(d, colour):
        cx, cy, r = 36 * S, 24 * S, 14 * S
        a = {"up": -90, "down": 90, "left": 180, "right": 0}[direction]
        def p(ang, rad):
            t = math.radians(a + ang)
            return cx + rad * math.cos(t), cy + rad * math.sin(t)
        d.polygon([p(0, r), p(140, r), p(180, r * 0.35), p(220, r)], fill=colour)
    return draw


def text_pic(text, size=18):
    def draw(d, colour):
        centred(d, 12 * S, text, font(size), colour)
    return draw


def crosshair(d, colour):
    cx, cy = 36 * S, 23 * S
    d.ellipse((cx - 10 * S, cy - 10 * S, cx + 10 * S, cy + 10 * S), outline=colour, width=2 * S)
    d.rectangle((cx - 3 * S, cy - 3 * S, cx + 3 * S, cy + 3 * S), fill=(255, 0, 255))


def mirror(axis, on):
    """MIRROR H / V: an "R" and its mirror image across a dashed axis"""
    img, d, frame = tile(on, BLUE)
    colour = (230, 235, 245) if on else (120, 120, 130)
    f = font(17)
    box = d.textbbox((0, 0), "R", font=f)
    gw, gh = box[2] - box[0], box[3] - box[1]
    glyph = Image.new("L", (gw, gh), 0)
    ImageDraw.Draw(glyph).text((-box[0], -box[1]), "R", font=f, fill=255)
    flipped = glyph.transpose(Image.FLIP_LEFT_RIGHT if axis == "h" else Image.FLIP_TOP_BOTTOM)
    dim = tuple(c // 2 for c in colour)
    if axis == "h":
        cx, y = 36 * S, 23 * S - gh // 2
        img.paste(colour, (cx - 3 * S - gw, y), glyph)
        img.paste(dim, (cx + 3 * S, y), flipped)
        for yy in range(6 * S, 38 * S, 5 * S):
            d.line((cx, yy, cx, yy + 2 * S), fill=frame, width=S)
    else:
        x, cy = 36 * S - gw // 2, 21 * S
        g2 = glyph.resize((gw, gh * 7 // 10))
        f2 = flipped.resize((gw, gh * 7 // 10))
        h2 = g2.size[1]
        img.paste(colour, (x, cy - 2 * S - h2), g2)
        img.paste(dim, (x, cy + 2 * S), f2)
        for xx in range(20 * S, 52 * S, 5 * S):
            d.line((xx, cy, xx + 2 * S, cy), fill=frame, width=S)
    centred(d, 41 * S, "MIRROR " + axis.upper(), font(9), (235, 235, 240))
    pill(d, on, frame)
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main(directory):
    out = lambda name, img: img.save(os.path.join(directory, name))
    for on in (True, False):
        st = "on" if on else "off"
        out(f"qvue-warp-{st}.bmp", toggle("WARP", on, bent_grid))
        out(f"qvue-warp-tune-{st}.bmp", toggle("TUNE", on, crosshair, AMBER))
        out(f"qvue-warp-grid-{st}.bmp", toggle("TEST GRID", on, lambda d, c: bent_grid(d, c, straight=True), AMBER))
        out(f"qvue-warp-mirror-h-{st}.bmp", mirror("h", on))
        out(f"qvue-warp-mirror-v-{st}.bmp", mirror("v", on))
        out(f"qvue-warp-step5-{st}.bmp", toggle("STEP", on, text_pic("5 px" if on else "1 px"), AMBER,
                                                 "5 px", "1 px"))
    # live_value bases: label at the top, the value is drawn at the bottom
    for name, label in (("qvue-warp-panel.png", "PANEL"), ("qvue-warp-handle.png", "HANDLE")):
        img, d, _ = tile(True, AMBER)
        centred(d, 8 * S, label, font(10), (235, 235, 240))
        out(name, img.resize((SIZE, SIZE), Image.LANCZOS))
    for direction in ("up", "down", "left", "right"):
        out(f"qvue-warp-{direction}.bmp", static(direction.upper(), arrow(direction), AMBER))
    out("qvue-warp-save.png", static("SAVE", text_pic("✓", 26), AMBER))
    out("qvue-warp-revert.bmp", static("REVERT", text_pic("↶", 26), AMBER))
    out("qvue-warp-reset.bmp", static("RESET", text_pic("0", 22), AMBER))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
