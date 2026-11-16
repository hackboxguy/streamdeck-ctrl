#!/usr/bin/env python3
"""The privacy keys' pictures, after the volume keys (make-volume-icons.py):

  privacy-on.png / privacy-off.png      the film toggle: on = green glow, a
                                        shield with a crossed-out eye; off =
                                        blue glow, an open eye; "PRIVACY" below
  privacy-level-up.png / -down.png      round glowing buttons (blue / amber) like
                                        volume-up/-down: a shield with an arrow
  privacy-level-value.png               the level key's base: a navy tile, a
                                        small shield on top, room for the value

    python3 images/make-privacy-icons.py screens/display-control
"""
import importlib.util
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("volume_icons", os.path.join(HERE, "make-volume-icons.py"))
vi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vi)

SIZE, WHITE, BLUE, AMBER = vi.SIZE, vi.WHITE, vi.BLUE, vi.AMBER
GREEN = (60, 220, 90)
NAVY = (8, 16, 40)


def shield(d, cx, cy, s, color=WHITE, fill_inner=None):
    """a shield centred at (cx, cy), s = its height"""
    w, h = s * 0.42, s / 2
    pts = [(cx, cy - h), (cx + w, cy - h * 0.7), (cx + w, cy - h * 0.05),
           (cx + w * 0.75, cy + h * 0.45), (cx, cy + h),
           (cx - w * 0.75, cy + h * 0.45), (cx - w, cy - h * 0.05), (cx - w, cy - h * 0.7)]
    d.polygon(pts, fill=color)
    if fill_inner:
        k = 0.8
        d.polygon([(cx + (x - cx) * k, cy + (y - cy) * k) for x, y in pts], fill=fill_inner)


def eye(d, cx, cy, w, color=WHITE, crossed=False, bg=NAVY):
    """an eye w wide; crossed: a slash through it"""
    h = w * 0.62                      # almond height
    lw = max(3, int(w * 0.08))
    n = 40
    xs = [cx - w / 2 + w * i / n for i in range(n + 1)]
    bulge = lambda x: (h / 2) * (1 - (2 * (x - cx) / w) ** 2)
    outline = [(x, cy - bulge(x)) for x in xs] + [(x, cy + bulge(x)) for x in reversed(xs)]
    d.line(outline + [outline[0]], fill=color, width=lw, joint="curve")
    r = h * 0.34                      # iris, a pupil cut out of it
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    r2 = r * 0.42
    d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill=bg)
    if crossed:
        s = w * 0.5
        d.line([(cx - s, cy + s * 0.75), (cx + s, cy - s * 0.75)], fill=bg, width=lw * 3)
        d.line([(cx - s, cy + s * 0.75), (cx + s, cy - s * 0.75)], fill=color, width=lw)


def round_button(up):
    color = BLUE if up else AMBER
    img = Image.new("RGB", (SIZE, SIZE))
    c, r = SIZE / 2, SIZE / 2 - 22
    circ = lambda d, col, w: d.ellipse([c - r, c - r, c + r, c + r], outline=col, width=w)
    img = vi.navy(img, lambda d, f: d.ellipse([c - r, c - r, c + r, c + r], fill=f))
    img = vi.glow_outline(img, circ, color, 18, 10, 7)
    d = ImageDraw.Draw(img)
    sy = c + (22 if up else -22)
    shield(d, c, sy, 112, WHITE, fill_inner=NAVY)
    eye(d, c, sy - 6, 54, WHITE, crossed=True)
    vi.arrow(d, c, c - 72 if up else c + 72, 54, up, WHITE)
    return img


def toggle(on):
    img = vi.tile(GREEN if on else BLUE)
    d = ImageDraw.Draw(img)
    if on:
        shield(d, SIZE / 2, 110, 132, GREEN, fill_inner=NAVY)
        eye(d, SIZE / 2, 104, 74, WHITE, crossed=True)
    else:
        eye(d, SIZE / 2, 110, 120, WHITE)
    vi.label(img, "PRIVACY", 200, size=36)
    return img


def main(directory):
    out = {
        "privacy-on.png": toggle(True),
        "privacy-off.png": toggle(False),
        "privacy-level-up.png": round_button(True),
        "privacy-level-down.png": round_button(False),
    }
    img = vi.tile(BLUE)                   # the level key: the value is drawn below
    d = ImageDraw.Draw(img)
    shield(d, SIZE / 2, 74, 76, WHITE, fill_inner=NAVY)
    eye(d, SIZE / 2, 70, 36, WHITE, crossed=True)
    out["privacy-level-value.png"] = img

    for name, im in out.items():
        path = os.path.join(directory, name)
        im.save(path, optimize=True)
        print(path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
