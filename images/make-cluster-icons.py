#!/usr/bin/env python3
"""Draw the display-control screen's Cluster Demo V2 keys that the stand-alone
qt-cluster-demo screen does not have (Atelier, Neo, Auto, DMS, Stop, DMS Link), in that
screen's style: 72x72, navy, a rounded border (green on / blue off), a white
glyph (grey when off) and a bold label.

    python3 images/make-cluster-icons.py screens/display-control
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

SIZE = 72
BG = (4, 8, 29)
BORDER = {"on": (38, 204, 74), "off": (47, 134, 216)}
GLYPH = {"on": (255, 255, 255), "off": (142, 144, 153)}
LABEL = (255, 255, 255)
FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fonts", "DejaVuSans-Bold.ttf")


def key(label, state, draw_glyph):
    im = Image.new("RGB", (SIZE, SIZE), BG)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((1, 1, SIZE - 2, SIZE - 2), radius=10, outline=BORDER[state], width=3)
    draw_glyph(d, GLYPH[state])
    font = ImageFont.truetype(FONT, 14 if len(label) <= 6 else 11)
    w = d.textlength(label, font=font)
    d.text(((SIZE - w) / 2, 52 if len(label) <= 6 else 54), label, font=font, fill=LABEL)
    return im


def atelier(d, c):      # a chronograph: the dial and three sub-dials
    d.ellipse((20, 8, 52, 40), outline=c, width=3)
    for x, y in ((29, 20), (43, 20), (36, 30)):
        d.ellipse((x - 4, y - 4, x + 4, y + 4), outline=c, width=2)


def neo(d, c):          # a road into the scene and its horizon
    d.line((12, 28, 60, 28), fill=c, width=2)
    d.polygon([(30, 28), (42, 28), (54, 44), (18, 44)], outline=c, width=3)
    d.line((36, 32, 36, 40), fill=c, width=2)


def auto(d, c):         # "A" in a circling arrow: the theme follows the vehicle
    d.arc((16, 6, 56, 46), start=40, end=330, fill=c, width=3)
    d.polygon([(52, 10), (56, 22), (45, 19)], fill=c)
    f = ImageFont.truetype(FONT, 18)
    w = d.textlength("A", font=f)
    d.text(((SIZE - w) / 2, 15), "A", font=f, fill=c)


def dms(d, c):          # an eye: driver monitoring
    d.arc((10, 8, 62, 52), start=208, end=332, fill=c, width=3)   # upper lid
    d.arc((10, -4, 62, 40), start=28, end=152, fill=c, width=3)   # lower lid
    d.ellipse((29, 15, 43, 29), fill=c)


def dms_link(d, c):     # a cable between two boxes: the Pi and the Xavier
    d.rectangle((10, 16, 24, 32), outline=c, width=3)
    d.rectangle((48, 16, 62, 32), outline=c, width=3)
    d.line((24, 24, 48, 24), fill=c, width=3)
    d.ellipse((32, 20, 40, 28), fill=c)


def stop(d, c):         # back to the launcher's home
    d.rounded_rectangle((24, 12, 48, 36), radius=4, fill=c)


def main(out_dir):
    for name, label, glyph in (("atelier", "ATELIER", atelier), ("neo", "NEO", neo),
                               ("auto", "AUTO", auto), ("dms", "DMS", dms)):
        for state in ("on", "off"):
            key(label, state, glyph).save(os.path.join(out_dir, f"cluster-{name}-{state}.bmp"))
    key("STOP", "off", stop).save(os.path.join(out_dir, "cluster-stop.bmp"))
    # a task key: one picture, the daemon draws the green/red state border
    key("DMS LINK", "off", dms_link).save(os.path.join(out_dir, "cluster-dms-link.bmp"))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
