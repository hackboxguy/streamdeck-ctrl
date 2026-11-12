"""Tests for streamdeck_ctrl.usb_override — the USB stick button layout."""

import json
import os
import threading
import time

import pytest

from streamdeck_ctrl import usb_override
from streamdeck_ctrl.daemon import StreamDeckDaemon
from streamdeck_ctrl.usb_override import (
    OverrideError,
    _usb_partitions,
    build_override,
    find_override,
    read_usb_file,
)

ICONS = os.path.join(os.path.dirname(__file__), "fixtures", "icons")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISPLAY_CONTROL = os.path.join(REPO, "screens", "display-control", "display-control.json")


def _base():
    return {
        "device": {"brightness": 80},
        "keys": [
            {"position": [0, 0], "label": "Home", "icon_type": "static",
             "icons": {"default": "icons/red.png"},
             "action": {"on_press": {"type": "script",
                                     "command": "{INSTALL_DIR}/scripts/home.sh"}}},
            {"position": [0, 1], "label": "Dimming", "icon_type": "toggle",
             "notification_id": "d.dim",
             "icons": {"on": "icons/green.png", "off": "icons/red.png"}},
            {"position": [0, 2], "label": "PixComp", "icon_type": "toggle",
             "notification_id": "d.pix",
             "enabled_when": {"key": "d.dim", "state": "on"},
             "icons": {"on": "icons/green.png", "off": "icons/red.png"}},
            {"position": [1, 0], "label": "Blue", "icon_type": "static",
             "icons": {"default": "icons/blue.png"}},
        ],
    }


class TestBuildOverride:
    def test_labels_pick_keys_in_file_order(self):
        cfg = build_override({"keys": ["Blue", "Home"]}, _base(), "/opt/sd")
        assert [k["label"] for k in cfg["keys"]] == ["Blue", "Home"]
        assert cfg["keys"][1]["action"]["on_press"]["command"] == "/opt/sd/scripts/home.sh"

    def test_whole_default_config_is_accepted(self):
        cfg = build_override(_base(), _base(), "/opt/sd")
        assert len(cfg["keys"]) == 4

    def test_copied_key_with_other_position_is_accepted(self):
        key = dict(_base()["keys"][3], position=[7, 7])
        cfg = build_override({"keys": [key]}, _base(), "/opt/sd")
        assert cfg["keys"][0]["position"] == [0, 0]  # renumbered in file order

    def test_positions_follow_file_order(self):
        cfg = build_override({"keys": ["Blue", "Dimming", "Home", "PixComp"]}, _base(), "/x")
        assert [k["position"] for k in cfg["keys"]] == [[0, 0], [0, 1], [0, 2], [0, 3]]

    def test_installed_path_equals_placeholder(self):
        key = _base()["keys"][0]
        key["action"]["on_press"]["command"] = "/opt/sd/scripts/home.sh"
        build_override({"keys": [key]}, _base(), "/opt/sd")

    def test_mixed_labels_and_objects(self):
        cfg = build_override({"keys": ["Home", _base()["keys"][3]]}, _base(), "/x")
        assert [k["label"] for k in cfg["keys"]] == ["Home", "Blue"]

    def test_changed_command_is_rejected(self):
        key = _base()["keys"][0]
        key["action"]["on_press"]["command"] = "rm -rf /"
        with pytest.raises(OverrideError, match="action"):
            build_override({"keys": [key]}, _base(), "/opt/sd")

    def test_added_field_is_rejected(self):
        key = dict(_base()["keys"][3], action={"on_press": {"type": "script",
                                                            "command": "evil"}})
        with pytest.raises(OverrideError, match="action"):
            build_override({"keys": [key]}, _base(), "/opt/sd")

    def test_null_is_a_blank_gap(self):
        cfg = build_override({"keys": ["Home", None, None, "Blue"]}, _base(), "/x")
        assert [k["label"] for k in cfg["keys"]] == ["Home", "(empty 2)", "(empty 3)", "Blue"]
        gap = cfg["keys"][1]
        assert gap["icons"]["default"] == ":blank:" and gap["action"] is None
        assert [k["position"] for k in cfg["keys"]] == [[0, 0], [0, 1], [0, 2], [0, 3]]

    def test_only_gaps_is_rejected(self):
        with pytest.raises(OverrideError, match="only gaps"):
            build_override({"keys": [None, None]}, _base(), "/x")

    def test_too_many_entries_is_rejected(self):
        with pytest.raises(OverrideError, match="more than"):
            build_override({"keys": ["Home"] + [None] * 600}, _base(), "/x")

    def test_unknown_label_is_rejected(self):
        with pytest.raises(OverrideError, match="not a key"):
            build_override({"keys": ["Nope"]}, _base(), "/x")

    def test_duplicate_is_rejected(self):
        with pytest.raises(OverrideError, match="twice"):
            build_override({"keys": ["Home", "Home"]}, _base(), "/x")

    def test_missing_dependency_is_rejected(self):
        with pytest.raises(OverrideError, match="depends on 'Dimming'"):
            build_override({"keys": ["PixComp"]}, _base(), "/x")

    def test_dependency_present_is_accepted(self):
        build_override({"keys": ["PixComp", "Dimming"]}, _base(), "/x")

    @pytest.mark.parametrize("usb", [[], {}, {"keys": []}, {"keys": "Home"},
                                     {"keys": [3]}])
    def test_malformed_is_rejected(self, usb):
        with pytest.raises(OverrideError):
            build_override(usb, _base(), "/x")

    def test_other_sections_come_from_default(self):
        usb = {"device": {"brightness": 5}, "notification": {"type": "unix_socket",
               "socket_path": "/tmp/evil.sock"}, "keys": ["Home"]}
        cfg = build_override(usb, _base(), "/x")
        assert cfg["device"] == {"brightness": 80}
        assert "notification" not in cfg


    def test_nav_position_may_come_from_the_file(self):
        cfg = build_override({"device": {"nav_position": "top"}, "keys": ["Home"]}, _base(), "/x")
        assert cfg["device"] == {"brightness": 80, "nav_position": "top"}

    def test_bad_nav_position_is_rejected(self):
        with pytest.raises(OverrideError, match="nav_position"):
            build_override({"device": {"nav_position": "left"}, "keys": ["Home"]}, _base(), "/x")


class TestRealSuperset:
    def test_mini_config_is_a_subset_of_display_control(self):
        with open(DISPLAY_CONTROL) as f:
            base = json.load(f)
        with open(DISPLAY_CONTROL.replace(".json", "-3x2.json")) as f:
            mini = json.load(f)
        cfg = build_override(mini, base)
        assert len(cfg["keys"]) == len(mini["keys"])

    def test_loads_with_real_icons(self):
        # superset positions such as [6, 3] must not reach the one-page bounds check
        from streamdeck_ctrl.usb_override import load_override_config
        with open(DISPLAY_CONTROL.replace(".json", "-3x2.json")) as f:
            text = f.read()
        cfg = load_override_config(DISPLAY_CONTROL, text)
        assert cfg["keys"][0]["label"] == "SDR/HDR Peru"

    def test_pixel_compensation_alone_is_rejected(self):
        with open(DISPLAY_CONTROL) as f:
            base = json.load(f)
        with pytest.raises(OverrideError, match="Local Dimming"):
            build_override({"keys": ["Pixel Compensation"]}, base)


# ---------------------------------------------------------------------------
# Finding the stick (fake /sys/block and /proc/mounts)
# ---------------------------------------------------------------------------


def _fake_disk(sys_block, name, removable="1", parts=("1",)):
    d = os.path.join(sys_block, name)
    os.makedirs(d)
    with open(os.path.join(d, "removable"), "w") as f:
        f.write(removable + "\n")
    for p in parts:
        os.makedirs(os.path.join(d, name + p))
        open(os.path.join(d, name + p, "partition"), "w").close()


class TestFindStick:
    def test_partitions_of_removable_disks_only(self, tmp_path):
        sb = tmp_path / "block"
        _fake_disk(str(sb), "sda", "0", ("1", "2"))
        _fake_disk(str(sb), "sdb", "1", ("1", "2"))
        _fake_disk(str(sb), "sdc", "1", ())
        assert _usb_partitions(str(sb)) == ["/dev/sdb1", "/dev/sdb2", "/dev/sdc"]

    def test_reads_file_on_mounted_stick(self, tmp_path):
        sb = tmp_path / "block"
        _fake_disk(str(sb), "sda", "1", ("1",))
        mnt = tmp_path / "media stick"
        mnt.mkdir()
        (mnt / "streamdeck-buttons.json").write_text('{"keys": ["Home"]}')
        mounts = tmp_path / "mounts"
        mounts.write_text(f"/dev/sda1 {str(mnt).replace(' ', chr(92) + '040')} vfat ro 0 0\n")
        path, text = read_usb_file(sys_block=str(sb), mounts=str(mounts), settle=False)
        assert path == str(mnt / "streamdeck-buttons.json")
        assert json.loads(text) == {"keys": ["Home"]}

    def test_no_stick(self, tmp_path):
        mounts = tmp_path / "mounts"
        mounts.write_text("")
        assert read_usb_file(sys_block=str(tmp_path), mounts=str(mounts),
                             settle=False) is None

    def test_unmounted_stick_is_mounted_and_unmounted(self, tmp_path, monkeypatch):
        sb = tmp_path / "block"
        _fake_disk(str(sb), "sda", "1", ("1",))
        mnt = tmp_path / "m"
        mnt.mkdir()
        (mnt / "streamdeck-buttons.json").write_text('{"keys": []}')
        mounts = tmp_path / "mounts"
        mounts.write_text("")
        calls = []

        class R:
            returncode = 0
            stderr = ""

        def fake_run(cmd, timeout=10):
            calls.append(cmd[:2])
            if cmd[1] == "mount":
                mounts.write_text(f"/dev/sda1 {mnt} vfat ro 0 0\n")
            else:
                mounts.write_text("")
            return R()

        monkeypatch.setattr(usb_override, "_run", fake_run)
        path, text = read_usb_file(sys_block=str(sb), mounts=str(mounts), settle=False)
        assert path == "/dev/sda1:/streamdeck-buttons.json"
        assert calls == [["udisksctl", "mount"], ["udisksctl", "unmount"]]


# ---------------------------------------------------------------------------
# find_override / daemon
# ---------------------------------------------------------------------------


def _write_base(tmp_path):
    os.symlink(ICONS, tmp_path / "icons")
    path = tmp_path / "display-control.json"
    path.write_text(json.dumps(_base()))
    return str(path)


def _stick(monkeypatch, text):
    monkeypatch.setattr(usb_override, "read_usb_file",
                        lambda **k: None if text is None else ("/media/x/f.json", text))


class TestFindOverride:
    def test_valid_file_is_loaded_with_default_icon_dir(self, tmp_path, monkeypatch):
        base = _write_base(tmp_path)
        _stick(monkeypatch, '{"keys": ["Blue", "Home"]}')
        cfg = find_override(base)
        assert [k["label"] for k in cfg["keys"]] == ["Blue", "Home"]
        assert cfg["keys"][0]["icons"]["default"] == str(tmp_path / "icons" / "blue.png")

    @pytest.mark.parametrize("text", [None, "{not json", '{"keys": ["Nope"]}',
                                      '{"keys": ["PixComp"]}'])
    def test_anything_else_falls_back(self, tmp_path, monkeypatch, text):
        base = _write_base(tmp_path)
        _stick(monkeypatch, text)
        assert find_override(base) is None

    def test_gaps_load_without_icon_files(self, tmp_path, monkeypatch):
        base = _write_base(tmp_path)
        _stick(monkeypatch, '{"keys": [null, "Home", null]}')
        cfg = find_override(base)
        assert [k["icons"]["default"] for k in cfg["keys"]][::2] == [":blank:", ":blank:"]

    def test_scan_error_falls_back(self, tmp_path, monkeypatch):
        base = _write_base(tmp_path)

        def boom(**k):
            raise RuntimeError("no sysfs")
        monkeypatch.setattr(usb_override, "read_usb_file", boom)
        assert find_override(base) is None


@pytest.mark.real_usb_scan
class TestDaemonUsesOverride:
    def _run(self, daemon):
        t = threading.Thread(target=daemon.run)
        t.start()
        for _ in range(50):
            if daemon._page_manager is not None:
                break
            time.sleep(0.05)
        daemon._shutdown_event.set()
        t.join(timeout=5)

    def test_override_keys_and_no_variant_switch(self, tmp_path, monkeypatch):
        base = _write_base(tmp_path)
        # a Mini variant exists, but the stick's file wins for every deck
        (tmp_path / "display-control-3x2.json").write_text(json.dumps(_base()))
        _stick(monkeypatch, '{"keys": ["Blue"]}')
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        daemon = StreamDeckDaemon(base, simulate=True, simulate_layout=(2, 3),
                                  socket_path=str(tmp_path / "s.sock"))
        self._run(daemon)
        assert [k["label"] for k in daemon._config["keys"]] == ["Blue"]
        assert daemon._config_path == base
        assert daemon._overridden
        # the sync scripts still report keys the stick's layout left out
        km = daemon._key_manager
        assert km.handle_notification("d.dim", state="on") == (True, None)
        ok, err = km.handle_notification("no.such", state="on")
        assert not ok and "unknown notification_id" in err

    def test_disabled_override_is_not_looked_for(self, tmp_path, monkeypatch):
        base = _write_base(tmp_path)

        def boom(**k):
            raise AssertionError("scanned")
        monkeypatch.setattr(usb_override, "read_usb_file", boom)
        daemon = StreamDeckDaemon(base, simulate=True, usb_override=False,
                                  socket_path=str(tmp_path / "s.sock"))
        self._run(daemon)
        assert len(daemon._config["keys"]) == 4
        assert daemon._key_manager._hidden_ids == frozenset()
