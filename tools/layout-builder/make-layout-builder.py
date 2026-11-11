#!/usr/bin/env python3
"""Build the offline Stream Deck layout builder page from a superset config.

    python3 tools/layout-builder/make-layout-builder.py \\
        --config screens/display-control/display-control.json \\
        -o streamdeck-layout-builder.html

The result is one self-contained HTML file (keys, icons and code inside, no
network): open it in any browser, drag the buttons wanted onto the deck, and
download streamdeck-buttons.json for the USB stick. Re-run this whenever keys
are added to the superset. The Pi still checks the downloaded file against
its own config (see the README, "Button layout from a USB stick").
"""

import argparse
import base64
import glob
import hashlib
import io
import json
import os
import sys
from datetime import date

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "template.html")
ICON_PX = 96  # preview size; the decks themselves use 72-96 px keys

# Which picture stands for a key in the builder
PREVIEW_ICON = {
    "static": ("default",),
    "toggle": ("off", "on"),
    "radio": ("off", "on"),
    "task": ("default",),
    "live_value": ("base",),
    "multistate": (),  # first state, below
}


def icon_data_uri(path, cache):
    if path in cache:
        return cache[path]
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((ICON_PX, ICON_PX), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "PNG", optimize=True)
    except (OSError, ValueError) as e:
        print(f"warning: icon {path}: {e}", file=sys.stderr)
        cache[path] = None
        return None
    cache[path] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    return cache[path]


def preview_icon(key, config_dir, cache):
    icons = key.get("icons", {})
    names = PREVIEW_ICON.get(key["icon_type"], ())
    if key["icon_type"] == "multistate" and key.get("states"):
        names = (key["states"][0],)
    for name in names or tuple(icons):
        rel = icons.get(name)
        if rel:
            path = rel if os.path.isabs(rel) else os.path.join(config_dir, rel)
            return icon_data_uri(path, cache)
    return None


def inert(key):
    """A key that does nothing - no action, no state (the superset's "Blank N"
    padding, which keeps later keys on their pages): left out of the builder,
    where an empty key is simply an empty slot."""
    action = key.get("action") or {}
    return not action.get("on_press") and not key.get("notification_id") \
        and "state_watch" not in key


def build_data(config_path):
    config_dir = os.path.dirname(os.path.abspath(config_path))
    with open(config_path) as f:
        raw = f.read()
    cfg = json.loads(raw)
    keys = cfg["keys"]
    by_id = {k["notification_id"]: k["label"] for k in keys if k.get("notification_id")}
    labels = [k["label"] for k in keys]
    if len(set(labels)) != len(labels):
        sys.exit("error: labels in the superset are not unique; the builder picks keys by label")

    cache = {}
    out_keys = []
    for k in keys:
        if inert(k):
            continue
        dep = (k.get("enabled_when") or {}).get("key")
        out_keys.append({
            "label": k["label"],
            "type": k["icon_type"],
            "icon": preview_icon(k, config_dir, cache),
            "needs": [by_id[dep]] if dep in by_id else [],
        })

    # Per-deck variants next to the superset make handy starting points
    stem = os.path.splitext(os.path.abspath(config_path))[0]
    # presets name every key in order; the builder leaves labels it does not
    # list (the inert keys) as empty keys, so the pages come out the same
    presets = [{"name": f"Everything ({len(out_keys)} keys)", "keys": labels}]
    for variant in sorted(glob.glob(stem + "-[0-9]*x[0-9]*.json")):
        try:
            with open(variant) as f:
                vkeys = [k["label"] for k in json.load(f)["keys"]]
        except (OSError, ValueError, KeyError) as e:
            print(f"warning: preset {variant}: {e}", file=sys.stderr)
            continue
        if all(l in set(labels) for l in vkeys):
            shown = sum(1 for l in vkeys if any(k["label"] == l for k in out_keys))
            presets.append({"name": f"{os.path.basename(variant)} ({shown} keys)",
                            "keys": vkeys})

    return {
        "superset": os.path.basename(config_path),
        "superset_sha": hashlib.sha256(raw.encode()).hexdigest()[:12],
        "generated": date.today().isoformat(),
        "default_layout": cfg.get("device", {}).get("layout", [3, 5]),
        "keys": out_keys,
        "presets": presets,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", required=True, help="superset config, e.g. display-control.json")
    ap.add_argument("-o", "--output", default="streamdeck-layout-builder.html")
    opts = ap.parse_args()

    data = build_data(opts.config)
    with open(TEMPLATE) as f:
        page = f.read()
    # "</" inside the JSON must not end the <script> element
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    if "/*__BUILDER_DATA__*/null" not in page:
        sys.exit("error: template has no /*__BUILDER_DATA__*/null placeholder")
    page = page.replace("/*__BUILDER_DATA__*/null", blob)
    with open(opts.output, "w") as f:
        f.write(page)
    missing = sum(1 for k in data["keys"] if not k["icon"])
    print(f"{opts.output}: {len(data['keys'])} keys, {len(data['presets'])} presets, "
          f"{os.path.getsize(opts.output) // 1024} KiB"
          + (f", {missing} without icon" if missing else ""))


if __name__ == "__main__":
    main()
