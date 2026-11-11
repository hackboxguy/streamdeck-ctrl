"""Button layout override from a USB stick.

At startup the daemon looks for ``streamdeck-buttons.json`` at the top level of
an attached USB stick. When it is there and valid, its keys replace the default
config's keys; otherwise the default config is used unchanged.

The file may only pick keys of the default (superset) config, never define its
own: a stick must not be able to run commands the default config does not
already have. Each entry of its ``keys`` array is either

  * a label of a default key, e.g. ``"HDMI 27"``, or
  * a full key object copied from the default config. It must be identical to
    that key, except for ``position``, which is ignored (``{INSTALL_DIR}`` and
    the installed path count as the same), or
  * ``null``: an empty key (black, does nothing) - a gap, so that the keys after
    it land where the layout builder put them.

Keys are laid out in the file's order (and renumbered in it), paginated for
whatever deck is attached.
Every key a chosen key depends on (``enabled_when``) must be chosen too.
Everything outside ``keys`` (device, notification) always comes from the
default config.
"""

import glob
import json
import logging
import os
import subprocess
from copy import deepcopy

from streamdeck_ctrl.icon_renderer import BLANK_ICON

logger = logging.getLogger(__name__)

USB_FILENAME = "streamdeck-buttons.json"
MAX_ENTRIES = 512  # keys plus gaps; far more than any deck pages sensibly
PLACEHOLDER = "{INSTALL_DIR}"
# The directory streamdeck_ctrl/ is installed in (what setup.sh puts in for {INSTALL_DIR})
INSTALL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class OverrideError(ValueError):
    """The USB file is not an acceptable subset of the default config."""


# ---------------------------------------------------------------------------
# Subset check
# ---------------------------------------------------------------------------


def _expand(obj, install_dir):
    """obj with every {INSTALL_DIR} replaced by install_dir."""
    return json.loads(json.dumps(obj).replace(PLACEHOLDER, install_dir))


def _without_position(key):
    return {k: v for k, v in key.items() if k != "position"}


def build_override(usb_cfg, base_cfg, install_dir=INSTALL_DIR):
    """The default config with its keys narrowed to the ones usb_cfg picks.

    Args:
        usb_cfg: the parsed USB file.
        base_cfg: the parsed default (superset) config.
        install_dir: what {INSTALL_DIR} stands for.

    Returns:
        dict: a copy of base_cfg whose keys are the chosen default keys, in
        usb_cfg's order.

    Raises:
        OverrideError: usb_cfg is not a subset of base_cfg.
    """
    if not isinstance(usb_cfg, dict) or not isinstance(usb_cfg.get("keys"), list):
        raise OverrideError("needs a \"keys\" array")
    if not usb_cfg["keys"]:
        raise OverrideError("\"keys\" is empty")

    base_cfg = _expand(base_cfg, install_dir)
    by_label = {k.get("label"): k for k in base_cfg.get("keys", [])}

    if len(usb_cfg["keys"]) > MAX_ENTRIES:
        raise OverrideError(f"more than {MAX_ENTRIES} entries in \"keys\"")

    chosen = []
    seen = set()
    for i, entry in enumerate(usb_cfg["keys"]):
        if entry is None:
            chosen.append(None)
            continue
        if isinstance(entry, str):
            label = entry
        elif isinstance(entry, dict):
            label = entry.get("label")
        else:
            raise OverrideError(f"keys[{i}] is neither a label nor a key object")
        base_key = by_label.get(label)
        if base_key is None:
            raise OverrideError(f"keys[{i}]: '{label}' is not a key of the default config")
        if isinstance(entry, dict):
            mine = _without_position(_expand(entry, install_dir))
            theirs = _without_position(base_key)
            if mine != theirs:
                fields = sorted(f for f in set(mine) | set(theirs)
                                if mine.get(f) != theirs.get(f))
                raise OverrideError(
                    f"keys[{i}] '{label}' differs from the default config's key "
                    f"in: {', '.join(fields)}")
        if label in seen:
            raise OverrideError(f"keys[{i}]: '{label}' is listed twice")
        seen.add(label)
        chosen.append(base_key)

    if not any(chosen):
        raise OverrideError("no keys, only gaps")

    # A key enabled by another key's state needs that key on the deck too
    chosen_ids = {k.get("notification_id") for k in chosen if k and k.get("notification_id")}
    by_id = {k.get("notification_id"): k for k in base_cfg.get("keys", [])
             if k.get("notification_id")}
    for key in filter(None, chosen):
        dep = (key.get("enabled_when") or {}).get("key")
        if dep and dep not in chosen_ids:
            dep_label = by_id.get(dep, {}).get("label", dep)
            raise OverrideError(
                f"'{key['label']}' depends on '{dep_label}', which is not chosen")

    # Keys are placed in this order; positions are only their identifiers, so
    # number them in that order (the superset's own would be out of bounds for
    # a subset that fits on one page)
    cols = (base_cfg.get("device") or {}).get("layout", [3, 5])[1]
    result = deepcopy(base_cfg)
    result["keys"] = [deepcopy(k) if k else _gap(i) for i, k in enumerate(chosen)]
    for i, key in enumerate(result["keys"]):
        key["position"] = [i // cols, i % cols]
    return result


def _gap(i):
    """An empty key: black, no action, no state."""
    return {"label": f"(empty {i + 1})", "icon_type": "static",
            "icons": {"default": BLANK_ICON}, "action": None}


# ---------------------------------------------------------------------------
# Finding the stick
# ---------------------------------------------------------------------------


def _usb_partitions(sys_block="/sys/block"):
    """/dev nodes of the filesystems on attached USB disks (partitions, else the disk)."""
    devs = []
    for block in sorted(glob.glob(os.path.join(sys_block, "sd*"))):
        name = os.path.basename(block)
        try:
            with open(os.path.join(block, "removable")) as f:
                removable = f.read().strip() == "1"
        except OSError:
            removable = False
        # USB disks that do not call themselves removable (SSDs, card readers)
        on_usb = "/usb" in os.path.realpath(block)
        if not (removable or on_usb):
            continue
        parts = sorted(os.path.basename(p) for p in glob.glob(os.path.join(block, name + "*"))
                       if os.path.exists(os.path.join(p, "partition")))
        devs.extend("/dev/" + p for p in (parts or [name]))
    return devs


def _mount_point(dev, mounts="/proc/mounts"):
    try:
        with open(mounts) as f:
            for line in f:
                fields = line.split()
                if len(fields) >= 2 and fields[0] == dev:
                    # /proc/mounts escapes spaces as \040
                    return fields[1].replace("\\040", " ")
    except OSError:
        pass
    return None


def _run(cmd, timeout=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("%s failed: %s", cmd[0], e)
        return None


def _read_if_present(path):
    if os.path.isfile(path):
        with open(path, "r") as f:
            return f.read()
    return None


def read_usb_file(filename=USB_FILENAME, sys_block="/sys/block", mounts="/proc/mounts",
                  settle=True):
    """(path, text) of the first USB stick's top-level filename, or None.

    A filesystem that is already mounted (e.g. by udisks2 at /media/pi/LABEL)
    is read where it is; one that is not is mounted read-only through udisks2
    just to read the file and unmounted again.
    """
    if settle:
        # At boot the stick may still be enumerating; returns at once when idle
        _run(["udevadm", "settle", "--timeout=5"], timeout=10)

    for dev in _usb_partitions(sys_block):
        mnt = _mount_point(dev, mounts)
        if mnt:
            path = os.path.join(mnt, filename)
            try:
                text = _read_if_present(path)
            except OSError as e:
                logger.warning("USB override: cannot read %s: %s", path, e)
                continue
            if text is not None:
                return path, text
            continue

        res = _run(["udisksctl", "mount", "-b", dev, "-o", "ro", "--no-user-interaction"])
        if res is None or res.returncode != 0:
            logger.debug("USB override: could not mount %s: %s", dev,
                         (res.stderr.strip() if res else "udisksctl missing"))
            continue
        mnt = _mount_point(dev, mounts)
        try:
            text = _read_if_present(os.path.join(mnt, filename)) if mnt else None
        except OSError as e:
            logger.warning("USB override: cannot read %s on %s: %s", filename, dev, e)
            text = None
        finally:
            _run(["udisksctl", "unmount", "-b", dev, "--no-user-interaction"])
        if text is not None:
            return f"{dev}:/{filename}", text
    return None


# ---------------------------------------------------------------------------
# Entry point for the daemon
# ---------------------------------------------------------------------------


def load_override_config(base_path, usb_text, source="USB file"):
    """Validate usb_text against the default config at base_path and load it.

    Returns the fully loaded config (as load_config returns it).
    Raises OverrideError / ValueError / jsonschema errors when it is unacceptable.
    """
    from streamdeck_ctrl.config import load_config

    try:
        usb_cfg = json.loads(usb_text)
    except json.JSONDecodeError as e:
        raise OverrideError(f"not valid JSON: {e}") from None
    with open(base_path, "r") as f:
        base_cfg = json.load(f)
    raw = build_override(usb_cfg, base_cfg)
    # Paths stay relative to the default config's directory, not the stick
    return load_config(base_path, data=raw)


def find_override(base_path, **kwargs):
    """The loaded override config from a USB stick, or None to use the default.

    Never raises: anything wrong with the stick or its file is logged and the
    default config is used.
    """
    try:
        found = read_usb_file(**kwargs)
    except Exception as e:  # noqa: BLE001 - a bad stick must not stop the daemon
        logger.warning("USB override: scanning USB sticks failed: %s", e)
        return None
    if found is None:
        logger.info("USB override: no %s on a USB stick, using %s",
                    USB_FILENAME, os.path.basename(base_path))
        return None
    source, text = found
    try:
        cfg = load_override_config(base_path, text, source)
    except Exception as e:  # noqa: BLE001
        logger.warning("USB override: %s rejected (%s); using %s", source, e,
                       os.path.basename(base_path))
        return None
    logger.info("USB override: using %s (%d keys)", source, len(cfg["keys"]))
    return cfg
