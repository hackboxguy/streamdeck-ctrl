#!/usr/bin/env python3
"""The page-6 OTA keys' pictures, made from the OLED-OTS IOC-Flash key's
picture the same way make-touch-flash-icon.py makes the OLED-IB one: the
chip's label becomes "OTA", and the two big lines name what the key updates
("IOC" / "983HH" / "FPGA" / "System") over "OTA-Update".

    python3 images/make-ota-icons.py screens/display-control
"""
import importlib.util
import os
import sys

_spec = importlib.util.spec_from_file_location(
    "make_touch_flash_icon",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "make-touch-flash-icon.py"))
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

ICONS = [("ota-ioc.png", "IOC"), ("ota-983.png", "983HH"),
         ("ota-fpga.png", "FPGA"), ("ota-system.png", "System")]


def main(directory):
    base.CHIP_LABEL = "OTA"
    for dst, first in ICONS:
        base.DST = dst
        base.LINES = [(first, (177, 723, 1075, 835)),
                      ("OTA-Update", (185, 877, 1071, 1007))]
        base.main(directory)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
