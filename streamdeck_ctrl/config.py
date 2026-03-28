"""JSON configuration loader, validator, and defaults injector."""

import json
import logging
import os
from copy import deepcopy

import jsonschema

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON Schema — derived from PRD sections 4.1–4.5
# ---------------------------------------------------------------------------

ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "on_press": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["script", "http"]},
                "command": {"type": "string"},
                "method": {"type": "string", "enum": ["GET", "POST", "PUT"]},
                "url": {"type": "string"},
                "body": {"type": "object"},
                "headers": {"type": "object"},
                "timeout_sec": {"type": "integer", "minimum": 1},
                "async": {"type": "boolean"},
            },
            "required": ["type"],
            "allOf": [
                {
                    "if": {"properties": {"type": {"const": "script"}}},
                    "then": {"required": ["command"]},
                },
                {
                    "if": {"properties": {"type": {"const": "http"}}},
                    "then": {"required": ["method", "url"]},
                },
            ],
        }
    },
    "required": ["on_press"],
}

KEY_COMMON = {
    "type": "object",
    "properties": {
        "position": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0},
            "minItems": 2,
            "maxItems": 2,
        },
        "label": {"type": "string"},
        "icon_type": {
            "type": "string",
            "enum": ["static", "toggle", "multistate", "live_value"],
        },
        "notification_id": {"type": "string"},
        "action": {
            "oneOf": [
                ACTION_SCHEMA,
                {"type": "null"},
            ]
        },
    },
    "required": ["position", "label", "icon_type"],
}

STATIC_KEY_SCHEMA = {
    "allOf": [
        KEY_COMMON,
        {
            "properties": {
                "icon_type": {"const": "static"},
                "icons": {
                    "type": "object",
                    "properties": {"default": {"type": "string"}},
                    "required": ["default"],
                },
            },
            "required": ["icons"],
        },
    ]
}

TOGGLE_KEY_SCHEMA = {
    "allOf": [
        KEY_COMMON,
        {
            "properties": {
                "icon_type": {"const": "toggle"},
                "icons": {
                    "type": "object",
                    "properties": {
                        "on": {"type": "string"},
                        "off": {"type": "string"},
                    },
                    "required": ["on", "off"],
                },
                "initial_state": {
                    "type": "string",
                    "enum": ["on", "off"],
                },
            },
            "required": ["icons"],
        },
    ]
}

MULTISTATE_KEY_SCHEMA = {
    "allOf": [
        KEY_COMMON,
        {
            "properties": {
                "icon_type": {"const": "multistate"},
                "states": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 3,
                },
                "icons": {"type": "object"},
                "initial_state": {"type": "string"},
            },
            "required": ["states", "icons"],
        },
    ]
}

LIVE_VALUE_KEY_SCHEMA = {
    "allOf": [
        KEY_COMMON,
        {
            "properties": {
                "icon_type": {"const": "live_value"},
                "icons": {
                    "type": "object",
                    "properties": {"base": {"type": "string"}},
                    "required": ["base"],
                },
                "live": {
                    "type": "object",
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": ["poll", "notify_only", "poll+notify"],
                        },
                        "poll_command": {"type": "string"},
                        "poll_interval_sec": {
                            "type": "integer",
                            "minimum": 1,
                        },
                        "format": {"type": "string"},
                        "text_anchor": {
                            "type": "string",
                            "enum": ["top", "center", "bottom"],
                        },
                        "text_color": {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"},
                        "font_size": {"type": "integer", "minimum": 1},
                        "font_path": {"type": "string"},
                    },
                    "required": ["source"],
                    "if": {
                        "properties": {
                            "source": {"enum": ["poll", "poll+notify"]}
                        }
                    },
                    "then": {
                        "required": ["poll_command", "poll_interval_sec"],
                    },
                },
            },
            "required": ["icons", "live"],
        },
    ]
}

CONFIG_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "device": {
            "type": "object",
            "properties": {
                "brightness": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                },
                "reconnect_timeout_sec": {
                    "type": "integer",
                    "minimum": 0,
                },
                "reconnect_interval_sec": {
                    "type": "integer",
                    "minimum": 1,
                },
                "layout": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "[rows, cols] — e.g. [3,5] for 15-key, [2,3] for Mini",
                },
            },
        },
        "notification": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["unix_socket"]},
                "socket_path": {"type": "string"},
                "state_persist_path": {"type": "string"},
            },
            "required": ["type", "socket_path"],
        },
        "keys": {
            "type": "array",
            "items": {
                "type": "object",
                "discriminator": {"propertyName": "icon_type"},
                "oneOf": [
                    STATIC_KEY_SCHEMA,
                    TOGGLE_KEY_SCHEMA,
                    MULTISTATE_KEY_SCHEMA,
                    LIVE_VALUE_KEY_SCHEMA,
                ],
            },
        },
    },
    "required": ["keys"],
}

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEVICE_DEFAULTS = {
    "brightness": 80,
    "layout": [3, 5],
    "reconnect_timeout_sec": 30,
    "reconnect_interval_sec": 2,
}

NOTIFICATION_DEFAULTS = {
    "type": "unix_socket",
    "socket_path": "/run/streamdeck-ctrl/notify.sock",
    "state_persist_path": "/run/streamdeck-ctrl/state.json",
}

LIVE_DEFAULTS = {
    "format": "{value}",
    "text_anchor": "bottom",
    "text_color": "#FFFFFF",
    "font_size": 14,
}

# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_config(path, *, validate_icons=True):
    """Load, validate, inject defaults, and resolve icon paths.

    Args:
        path: Path to the JSON config file.
        validate_icons: If True, verify that all referenced icon files exist.

    Returns:
        dict: The fully resolved configuration.

    Raises:
        FileNotFoundError: If the config file or any icon file is missing.
        json.JSONDecodeError: If the JSON is malformed.
        jsonschema.ValidationError: If the config violates the schema.
        ValueError: If semantic validation fails (duplicate positions, etc.).
    """
    path = os.path.abspath(path)
    config_dir = os.path.dirname(path)

    with open(path, "r") as f:
        cfg = json.load(f)

    # --- schema validation ---
    jsonschema.validate(cfg, CONFIG_SCHEMA)

    # --- inject defaults ---
    cfg.setdefault("device", {})
    for k, v in DEVICE_DEFAULTS.items():
        cfg["device"].setdefault(k, v)

    cfg.setdefault("notification", {})
    for k, v in NOTIFICATION_DEFAULTS.items():
        cfg["notification"].setdefault(k, v)

    for key in cfg["keys"]:
        _inject_key_defaults(key)

    # --- semantic validation ---
    layout = cfg["device"]["layout"]
    _validate_positions(cfg["keys"], max_rows=layout[0], max_cols=layout[1])
    _validate_notification_ids(cfg["keys"])
    _validate_multistate_keys(cfg["keys"])
    _warn_stateful_keys_without_notification_id(cfg["keys"])

    # --- resolve icon paths ---
    _resolve_icon_paths(cfg["keys"], config_dir)

    # --- validate icon files exist ---
    if validate_icons:
        _validate_icon_files(cfg["keys"])

    logger.info("Config loaded: %s (%d keys)", path, len(cfg["keys"]))
    return cfg


def _inject_key_defaults(key):
    """Inject per-key defaults based on icon_type."""
    icon_type = key["icon_type"]

    if icon_type == "toggle":
        key.setdefault("initial_state", "off")
    elif icon_type == "multistate":
        key.setdefault("initial_state", key["states"][0])
    elif icon_type == "live_value":
        key.setdefault("live", {})
        for k, v in LIVE_DEFAULTS.items():
            key["live"].setdefault(k, v)


def _validate_positions(keys, max_rows=3, max_cols=5):
    """Ensure no two keys share the same position and all are within bounds."""
    seen = {}
    for key in keys:
        pos = tuple(key["position"])
        row, col = pos
        if row >= max_rows or col >= max_cols:
            raise ValueError(
                f"Key '{key['label']}': position {list(pos)} is out of bounds "
                f"for {max_rows}x{max_cols} deck (max row={max_rows - 1}, "
                f"max col={max_cols - 1})"
            )
        if pos in seen:
            raise ValueError(
                f"Duplicate position {list(pos)}: "
                f"'{key['label']}' and '{seen[pos]}'"
            )
        seen[pos] = key["label"]


def _validate_notification_ids(keys):
    """Ensure no two keys share the same notification_id."""
    seen = {}
    for key in keys:
        nid = key.get("notification_id")
        if nid is None:
            continue
        if nid in seen:
            raise ValueError(
                f"Duplicate notification_id '{nid}': "
                f"'{key['label']}' and '{seen[nid]}'"
            )
        seen[nid] = key["label"]


def _validate_multistate_keys(keys):
    """Validate multistate-specific constraints."""
    for key in keys:
        if key["icon_type"] != "multistate":
            continue
        states = key["states"]
        # Every state must have an icon
        for state in states:
            if state not in key["icons"]:
                raise ValueError(
                    f"Key '{key['label']}': multistate missing icon "
                    f"for state '{state}'"
                )
        # initial_state must be valid
        if key.get("initial_state") and key["initial_state"] not in states:
            raise ValueError(
                f"Key '{key['label']}': initial_state "
                f"'{key['initial_state']}' not in states {states}"
            )


def _warn_stateful_keys_without_notification_id(keys):
    """Warn about toggle/multistate/live_value keys without notification_id."""
    for key in keys:
        if key["icon_type"] in ("toggle", "multistate", "live_value"):
            if not key.get("notification_id"):
                logger.warning(
                    "Key '%s' (type=%s) has no notification_id — "
                    "state will not persist across restarts and cannot "
                    "be updated via notifications",
                    key["label"], key["icon_type"],
                )


def _resolve_icon_paths(keys, config_dir):
    """Resolve relative icon paths to absolute paths based on config dir."""
    for key in keys:
        icons = key.get("icons", {})
        for icon_key, icon_path in icons.items():
            if not os.path.isabs(icon_path):
                icons[icon_key] = os.path.normpath(
                    os.path.join(config_dir, icon_path)
                )
        # Also resolve font_path for live_value keys
        if key["icon_type"] == "live_value":
            live = key.get("live", {})
            font_path = live.get("font_path")
            if font_path and not os.path.isabs(font_path):
                live["font_path"] = os.path.normpath(
                    os.path.join(config_dir, font_path)
                )


def _validate_icon_files(keys):
    """Verify all referenced icon files exist on disk."""
    for key in keys:
        icons = key.get("icons", {})
        for icon_key, icon_path in icons.items():
            if not os.path.isfile(icon_path):
                raise FileNotFoundError(
                    f"Icon not found: {icon_path} "
                    f"(key '{key['label']}', icons.{icon_key})"
                )
