#!/usr/bin/env python3
"""The Stop key's pictures, after the volume keys (make-volume-icons.py):

  stop-on.png    something plays or runs: a red glowing tile, a white stop
                 square, "STOP" below
  stop-off.png   nothing to stop (the launcher's home screen): the same, dim grey

    python3 images/make-stop-icons.py screens/display-control
"""
import importlib.util
import os
import sys

from PIL import ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("volume_icons", os.path.join(HERE, "make-volume-icons.py"))
vi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vi)

SIZE, WHITE, RED = vi.SIZE, vi.WHITE, vi.RED
GREY = (90, 96, 110)
DIM = (120, 126, 140)


def stop(on):
    img = vi.tile(RED if on else GREY)
    d = ImageDraw.Draw(img)
    s = 100
    cx, cy = SIZE / 2, 112
    d.rounded_rectangle([cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2], radius=14,
                        fill=WHITE if on else DIM)
    vi.label(img, "STOP", 206, size=44)
    return img


def main(directory):
    for name, im in {"stop-on.png": stop(True), "stop-off.png": stop(False)}.items():
        path = os.path.join(directory, name)
        im.save(path, optimize=True)
        print(path)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
