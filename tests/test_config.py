"""Tests for streamdeck_ctrl.config — JSON loading, validation, defaults."""

import json
import os
import pytest
import tempfile
import shutil

from streamdeck_ctrl.config import load_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
ICONS = os.path.join(FIXTURES, "icons")


def _write_config(tmpdir, cfg, icons_dir=None):
    """Write a config dict to a temp JSON file, optionally symlink icons."""
    config_path = os.path.join(tmpdir, "layout.json")
    with open(config_path, "w") as f:
        json.dump(cfg, f)
    # Create or symlink icons dir so icon paths resolve
    dst_icons = os.path.join(tmpdir, "icons")
    if icons_dir and not os.path.exists(dst_icons):
        os.symlink(icons_dir, dst_icons)
    return config_path


def _minimal_static(pos=(0, 0), label="Test", icon="icons/red.png"):
    return {
        "position": list(pos),
        "label": label,
        "icon_type": "static",
        "icons": {"default": icon},
    }


def _minimal_toggle(pos=(0, 0), label="Toggle"):
    return {
        "position": list(pos),
        "label": label,
        "icon_type": "toggle",
        "icons": {"on": "icons/green.png", "off": "icons/red.png"},
    }


def _minimal_multistate(pos=(0, 0), label="Multi"):
    return {
        "position": list(pos),
        "label": label,
        "icon_type": "multistate",
        "states": ["a", "b", "c"],
        "icons": {"a": "icons/red.png", "b": "icons/green.png", "c": "icons/blue.png"},
    }


def _minimal_live(pos=(0, 0), label="Live"):
    return {
        "position": list(pos),
        "label": label,
        "icon_type": "live_value",
        "icons": {"base": "icons/gray.png"},
        "live": {"source": "notify_only"},
    }


def _base_cfg(keys):
    return {"keys": keys}


@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


# ---------------------------------------------------------------------------
# Valid configs
# ---------------------------------------------------------------------------


class TestValidConfigs:
    def test_minimal_static_key(self, tmpdir):
        cfg_path = _write_config(tmpdir, _base_cfg([_minimal_static()]), ICONS)
        cfg = load_config(cfg_path)
        assert len(cfg["keys"]) == 1
        assert cfg["keys"][0]["icon_type"] == "static"

    def test_toggle_key_with_defaults(self, tmpdir):
        cfg_path = _write_config(tmpdir, _base_cfg([_minimal_toggle()]), ICONS)
        cfg = load_config(cfg_path)
        key = cfg["keys"][0]
        assert key["initial_state"] == "off"  # default injected

    def test_multistate_key_with_defaults(self, tmpdir):
        cfg_path = _write_config(tmpdir, _base_cfg([_minimal_multistate()]), ICONS)
        cfg = load_config(cfg_path)
        key = cfg["keys"][0]
        assert key["initial_state"] == "a"  # defaults to first state

    def test_live_value_defaults(self, tmpdir):
        cfg_path = _write_config(tmpdir, _base_cfg([_minimal_live()]), ICONS)
        cfg = load_config(cfg_path)
        live = cfg["keys"][0]["live"]
        assert live["format"] == "{value}"
        assert live["text_anchor"] == "bottom"
        assert live["text_color"] == "#FFFFFF"
        assert live["font_size"] == 14

    def test_device_defaults_injected(self, tmpdir):
        cfg_path = _write_config(tmpdir, _base_cfg([_minimal_static()]), ICONS)
        cfg = load_config(cfg_path)
        assert cfg["device"]["brightness"] == 80
        assert cfg["device"]["layout"] == [3, 5]
        assert cfg["device"]["reconnect_timeout_sec"] == 30
        assert cfg["device"]["reconnect_interval_sec"] == 2

    def test_custom_layout(self, tmpdir):
        cfg = _base_cfg([_minimal_static(pos=(1, 2))])
        cfg["device"] = {"layout": [2, 3]}
        cfg_path = _write_config(tmpdir, cfg, ICONS)
        result = load_config(cfg_path)
        assert result["device"]["layout"] == [2, 3]

    def test_custom_layout_rejects_out_of_bounds(self, tmpdir):
        cfg = _base_cfg([_minimal_static(pos=(0, 3))])
        cfg["device"] = {"layout": [2, 3]}
        cfg_path = _write_config(tmpdir, cfg, ICONS)
        with pytest.raises(ValueError, match="out of bounds"):
            load_config(cfg_path)

    def test_notification_defaults_injected(self, tmpdir):
        cfg_path = _write_config(tmpdir, _base_cfg([_minimal_static()]), ICONS)
        cfg = load_config(cfg_path)
        assert cfg["notification"]["type"] == "unix_socket"
        assert cfg["notification"]["socket_path"] == "/run/streamdeck-ctrl/notify.sock"

    def test_device_overrides_preserved(self, tmpdir):
        cfg = _base_cfg([_minimal_static()])
        cfg["device"] = {"brightness": 50}
        cfg_path = _write_config(tmpdir, cfg, ICONS)
        result = load_config(cfg_path)
        assert result["device"]["brightness"] == 50
        assert result["device"]["reconnect_timeout_sec"] == 30  # default still set

    def test_multiple_keys(self, tmpdir):
        keys = [
            _minimal_static(pos=(0, 0), label="K1"),
            _minimal_toggle(pos=(0, 1), label="K2"),
            _minimal_multistate(pos=(1, 0), label="K3"),
            _minimal_live(pos=(1, 1), label="K4"),
        ]
        cfg_path = _write_config(tmpdir, _base_cfg(keys), ICONS)
        cfg = load_config(cfg_path)
        assert len(cfg["keys"]) == 4

    def test_icon_paths_resolved_to_absolute(self, tmpdir):
        cfg_path = _write_config(tmpdir, _base_cfg([_minimal_static()]), ICONS)
        cfg = load_config(cfg_path)
        icon_path = cfg["keys"][0]["icons"]["default"]
        assert os.path.isabs(icon_path)

    def test_action_with_script(self, tmpdir):
        key = _minimal_static()
        key["action"] = {
            "on_press": {
                "type": "script",
                "command": "/bin/echo hello",
                "async": True,
            }
        }
        cfg_path = _write_config(tmpdir, _base_cfg([key]), ICONS)
        cfg = load_config(cfg_path)
        assert cfg["keys"][0]["action"]["on_press"]["type"] == "script"

    def test_action_with_http(self, tmpdir):
        key = _minimal_static()
        key["action"] = {
            "on_press": {
                "type": "http",
                "method": "POST",
                "url": "http://localhost/api",
                "body": {"key": "{state}"},
                "async": True,
            }
        }
        cfg_path = _write_config(tmpdir, _base_cfg([key]), ICONS)
        cfg = load_config(cfg_path)
        assert cfg["keys"][0]["action"]["on_press"]["method"] == "POST"

    def test_null_action(self, tmpdir):
        key = _minimal_static()
        key["action"] = None
        cfg_path = _write_config(tmpdir, _base_cfg([key]), ICONS)
        cfg = load_config(cfg_path)
        assert cfg["keys"][0]["action"] is None

    def test_live_value_with_poll_source(self, tmpdir):
        key = _minimal_live()
        key["live"] = {
            "source": "poll",
            "poll_command": "/usr/bin/cat /sys/class/thermal/thermal_zone0/temp",
            "poll_interval_sec": 5,
        }
        cfg_path = _write_config(tmpdir, _base_cfg([key]), ICONS)
        cfg = load_config(cfg_path)
        assert cfg["keys"][0]["live"]["source"] == "poll"


# ---------------------------------------------------------------------------
# Schema violations
# ---------------------------------------------------------------------------


class TestSchemaViolations:
    def test_missing_keys_array(self, tmpdir):
        cfg_path = _write_config(tmpdir, {"device": {}})
        with pytest.raises(Exception):  # jsonschema.ValidationError
            load_config(cfg_path, validate_icons=False)

    def test_key_missing_position(self, tmpdir):
        key = {"label": "X", "icon_type": "static", "icons": {"default": "x.png"}}
        cfg_path = _write_config(tmpdir, _base_cfg([key]))
        with pytest.raises(Exception):
            load_config(cfg_path, validate_icons=False)

    def test_key_missing_label(self, tmpdir):
        key = {"position": [0, 0], "icon_type": "static", "icons": {"default": "x.png"}}
        cfg_path = _write_config(tmpdir, _base_cfg([key]))
        with pytest.raises(Exception):
            load_config(cfg_path, validate_icons=False)

    def test_invalid_icon_type(self, tmpdir):
        key = {
            "position": [0, 0],
            "label": "X",
            "icon_type": "invalid_type",
            "icons": {"default": "x.png"},
        }
        cfg_path = _write_config(tmpdir, _base_cfg([key]))
        with pytest.raises(Exception):
            load_config(cfg_path, validate_icons=False)

    def test_brightness_out_of_range(self, tmpdir):
        cfg = _base_cfg([_minimal_static()])
        cfg["device"] = {"brightness": 200}
        cfg_path = _write_config(tmpdir, cfg)
        with pytest.raises(Exception):
            load_config(cfg_path, validate_icons=False)

    def test_toggle_missing_icons(self, tmpdir):
        key = {
            "position": [0, 0],
            "label": "X",
            "icon_type": "toggle",
            "icons": {"on": "icons/green.png"},  # missing 'off'
        }
        cfg_path = _write_config(tmpdir, _base_cfg([key]))
        with pytest.raises(Exception):
            load_config(cfg_path, validate_icons=False)

    def test_live_value_poll_missing_command(self, tmpdir):
        key = _minimal_live()
        key["live"] = {"source": "poll"}  # missing poll_command
        cfg_path = _write_config(tmpdir, _base_cfg([key]))
        with pytest.raises(Exception):
            load_config(cfg_path, validate_icons=False)

    def test_invalid_text_color(self, tmpdir):
        key = _minimal_live()
        key["live"] = {"source": "notify_only", "text_color": "red"}
        cfg_path = _write_config(tmpdir, _base_cfg([key]))
        with pytest.raises(Exception):
            load_config(cfg_path, validate_icons=False)

    def test_script_action_missing_command(self, tmpdir):
        key = _minimal_static()
        key["action"] = {"on_press": {"type": "script"}}  # missing command
        cfg_path = _write_config(tmpdir, _base_cfg([key]))
        with pytest.raises(Exception):
            load_config(cfg_path, validate_icons=False)

    def test_http_action_missing_url(self, tmpdir):
        key = _minimal_static()
        key["action"] = {"on_press": {"type": "http", "method": "GET"}}
        cfg_path = _write_config(tmpdir, _base_cfg([key]))
        with pytest.raises(Exception):
            load_config(cfg_path, validate_icons=False)


# ---------------------------------------------------------------------------
# Semantic validation
# ---------------------------------------------------------------------------


class TestSemanticValidation:
    def test_duplicate_positions_rejected(self, tmpdir):
        keys = [
            _minimal_static(pos=(0, 0), label="K1"),
            _minimal_static(pos=(0, 0), label="K2", icon="icons/blue.png"),
        ]
        cfg_path = _write_config(tmpdir, _base_cfg(keys), ICONS)
        with pytest.raises(ValueError, match="Duplicate position"):
            load_config(cfg_path)

    def test_multistate_missing_icon_for_state(self, tmpdir):
        key = _minimal_multistate()
        del key["icons"]["c"]  # state 'c' has no icon
        cfg_path = _write_config(tmpdir, _base_cfg([key]), ICONS)
        with pytest.raises(ValueError, match="missing icon"):
            load_config(cfg_path)

    def test_multistate_invalid_initial_state(self, tmpdir):
        key = _minimal_multistate()
        key["initial_state"] = "nonexistent"
        cfg_path = _write_config(tmpdir, _base_cfg([key]), ICONS)
        with pytest.raises(ValueError, match="initial_state"):
            load_config(cfg_path)

    def test_position_out_of_bounds_row(self, tmpdir):
        key = _minimal_static(pos=(3, 0), label="OOB")
        cfg_path = _write_config(tmpdir, _base_cfg([key]), ICONS)
        with pytest.raises(ValueError, match="out of bounds"):
            load_config(cfg_path)

    def test_position_out_of_bounds_col(self, tmpdir):
        key = _minimal_static(pos=(0, 5), label="OOB")
        cfg_path = _write_config(tmpdir, _base_cfg([key]), ICONS)
        with pytest.raises(ValueError, match="out of bounds"):
            load_config(cfg_path)

    def test_position_max_valid(self, tmpdir):
        key = _minimal_static(pos=(2, 4), label="MaxValid")
        cfg_path = _write_config(tmpdir, _base_cfg([key]), ICONS)
        cfg = load_config(cfg_path)
        assert cfg["keys"][0]["position"] == [2, 4]

    def test_duplicate_notification_id_rejected(self, tmpdir):
        keys = [
            _minimal_toggle(pos=(0, 0), label="K1"),
            _minimal_toggle(pos=(0, 1), label="K2"),
        ]
        keys[0]["notification_id"] = "same.id"
        keys[1]["notification_id"] = "same.id"
        cfg_path = _write_config(tmpdir, _base_cfg(keys), ICONS)
        with pytest.raises(ValueError, match="Duplicate notification_id"):
            load_config(cfg_path)

    def test_missing_icon_file(self, tmpdir):
        key = _minimal_static(icon="icons/nonexistent.png")
        cfg_path = _write_config(tmpdir, _base_cfg([key]), ICONS)
        with pytest.raises(FileNotFoundError, match="Icon not found"):
            load_config(cfg_path)

    def test_skip_icon_validation(self, tmpdir):
        """validate_icons=False should skip file existence check."""
        key = _minimal_static(icon="icons/nonexistent.png")
        cfg_path = _write_config(tmpdir, _base_cfg([key]))
        cfg = load_config(cfg_path, validate_icons=False)
        assert len(cfg["keys"]) == 1


# ---------------------------------------------------------------------------
# File errors
# ---------------------------------------------------------------------------


class TestFileErrors:
    def test_config_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/layout.json")

    def test_invalid_json(self, tmpdir):
        path = os.path.join(tmpdir, "bad.json")
        with open(path, "w") as f:
            f.write("{invalid json")
        with pytest.raises(json.JSONDecodeError):
            load_config(path)
