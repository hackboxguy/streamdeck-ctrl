#!/usr/bin/env python3
"""The Display Power toggle key's two pictures, in the style of the Pixel
Compensation key (dark rounded tile, a picture, a label and an ON/OFF pill
with a power symbol): a monitor that is lit (on, blue frame) or dark (off,
grey frame). Drawn at 4x and scaled down to the deck's 72x72 for clean edges.

    python3 images/make-display-power-icon.py screens/display-control
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts", "DejaVuSans-Bold.ttf")
SIZE = 72
S = 4                      # supersampling
W = SIZE * S


def font(px):
    return ImageFont.truetype(FONT, px * S)


def centred(draw, y, text, f, fill):
    box = draw.textbbox((0, 0), text, font=f)
    draw.text(((W - (box[2] - box[0])) // 2 - box[0], y), text, font=f, fill=fill)


def power_symbol(draw, cx, cy, r, colour, width):
    draw.arc((cx - r, cy - r, cx + r, cy + r), start=-60, end=240, fill=colour, width=width)
    draw.line((cx, cy - r - width // 2, cx, cy), fill=colour, width=width)


def make(on):
    frame = (40, 140, 255) if on else (110, 110, 120)
    img = Image.new("RGB", (W, W), (0, 0, 0))
    d = ImageDraw.Draw(img)
    # tile
    d.rounded_rectangle((2 * S, 2 * S, W - 2 * S, W - 2 * S), radius=9 * S,
                        fill=(10, 14, 28) if on else (16, 16, 18), outline=frame, width=2 * S)
    # monitor: bezel, screen, stand
    x0, y0, x1, y1 = 18 * S, 9 * S, 54 * S, 33 * S
    d.rounded_rectangle((x0, y0, x1, y1), radius=2 * S, fill=(200, 205, 215), outline=None)
    if on:
        # lit screen: a blue-to-cyan gradient
        for i in range(y1 - y0 - 4 * S):
            t = i / (y1 - y0 - 4 * S)
            c = (int(30 + 40 * t), int(110 + 90 * t), int(255 - 30 * t))
            d.line((x0 + 2 * S, y0 + 2 * S + i, x1 - 2 * S, y0 + 2 * S + i), fill=c)
    else:
        d.rectangle((x0 + 2 * S, y0 + 2 * S, x1 - 2 * S, y1 - 2 * S), fill=(8, 8, 10))
    d.rectangle((33 * S, y1, 39 * S, 37 * S), fill=(200, 205, 215))
    d.rounded_rectangle((27 * S, 37 * S, 45 * S, 39 * S), radius=S, fill=(200, 205, 215))
    # label
    centred(d, 41 * S, "DISPLAY", font(9), (235, 235, 240))
    # ON / OFF pill with a power symbol
    px0, py0, px1, py1 = 16 * S, 54 * S, 56 * S, 66 * S
    d.rounded_rectangle((px0, py0, px1, py1), radius=6 * S,
                        fill=(20, 60, 140) if on else (40, 40, 44), outline=frame, width=S)
    power_symbol(d, px0 + 9 * S, (py0 + py1) // 2, 3 * S, (255, 255, 255), max(1, S))
    f = font(8)
    label = "ON" if on else "OFF"
    box = d.textbbox((0, 0), label, font=f)
    d.text((px0 + 17 * S - box[0], (py0 + py1) // 2 - (box[3] + box[1]) // 2), label,
           font=f, fill=(255, 255, 255))
    return img.resize((SIZE, SIZE), Image.LANCZOS)


def main(directory):
    make(True).save(os.path.join(directory, "display-power-on.bmp"))
    make(False).save(os.path.join(directory, "display-power-off.bmp"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
