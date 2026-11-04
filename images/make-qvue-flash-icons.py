#!/usr/bin/env python3
"""The QVue IOC-Flash keys' pictures, made from the OLED-OTS IOC-Flash key's
picture the same way make-touch-flash-icon.py makes the OLED-IB one (same
boxes, same font fitting): the chip's label becomes "QVUE", and the two big
lines become "Qvue-Legacy" / "IOC-Flash", "Qvue-New" / "IOC-Flash" and
"Qvue-New" / "FPGA-Flash".

    python3 images/make-qvue-flash-icons.py screens/display-control
"""
import importlib.util
import os
import sys

_spec = importlib.util.spec_from_file_location(
    "make_touch_flash_icon",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "make-touch-flash-icon.py"))
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

# (output file, first big line, second big line)
ICONS = [("qvue-legacy-ioc-flash.png", "Qvue-Legacy", "IOC-Flash"),
         ("qvue-new-ioc-flash.png", "Qvue-New", "IOC-Flash"),
         ("qvue-new-fpga-flash.png", "Qvue-New", "FPGA-Flash")]


def main(directory):
    base.CHIP_LABEL = "QVUE"
    for dst, first, second in ICONS:
        base.DST = dst
        base.LINES = [(first, (177, 723, 1075, 835)),
                      (second, (185, 877, 1071, 1007))]
        base.main(directory)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
