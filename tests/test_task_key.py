"""Tests for the `task` key type — blinking border, success/failure outcome."""

import json
import os
import queue
import shutil
import socket
import tempfile
import threading
import time

import jsonschema
import pytest

from streamdeck_ctrl.config import load_config
from streamdeck_ctrl.daemon import StreamDeckDaemon
from streamdeck_ctrl.icon_renderer import clear_cache, render_bordered_image
from streamdeck_ctrl.key_manager import KeyState
from streamdeck_ctrl.page_manager import PageManager


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "icons")
GRAY = os.path.join(FIXTURES, "gray.png")


def task_cfg(**overrides):
    cfg = {
        "position": [0, 0],
        "label": "Flash",
        "icon_type": "task",
        "icons": {"default": "/icons/flash.png"},
        "initial_state": "idle",
        "notification_id": "test.flash",
        "task": {
            "blink_interval_sec": 0.5,
            "border_width": 6,
            "colors": {
                "running": "#00FF00",
                "success": "#00FF00",
                "failure": "#FF0000",
            },
        },
        "action": {"on_press": {"type": "script", "command": "flash.sh"}},
    }
    cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class TestTaskStateMachine:
    def test_starts_idle_without_border(self):
        ks = KeyState(task_cfg(), queue.Queue(maxsize=10))
        assert ks.state == "idle"
        assert ks.get_render_info()["border_color"] is None

    def test_press_starts_running_and_fires_action(self):
        ks = KeyState(task_cfg(), queue.Queue(maxsize=10))
        state, action = ks.press()
        assert state == "running"
        assert action is not None
        assert ks.get_render_info()["border_color"] == "#00FF00"

    def test_press_while_running_is_swallowed(self):
        """A second flash on top of the first would corrupt the target."""
        ks = KeyState(task_cfg(), queue.Queue(maxsize=10))
        ks.press()
        state, action = ks.press()
        assert state == "running"
        assert action is None

    def test_blink_alternates_border(self):
        ks = KeyState(task_cfg(), queue.Queue(maxsize=10))
        ks.press()
        assert ks.get_render_info()["border_color"] == "#00FF00"
        assert ks.advance_blink() is True
        assert ks.get_render_info()["border_color"] is None
        assert ks.advance_blink() is True
        assert ks.get_render_info()["border_color"] == "#00FF00"

    def test_blink_is_a_no_op_unless_running(self):
        ks = KeyState(task_cfg(), queue.Queue(maxsize=10))
        assert ks.advance_blink() is False
        ks.notify_state("success")
        assert ks.advance_blink() is False

    def test_success_is_a_solid_green_border(self):
        ks = KeyState(task_cfg(), queue.Queue(maxsize=10))
        ks.press()
        ok, err = ks.notify_state("success")
        assert (ok, err) == (True, None)
        assert ks.get_render_info()["border_color"] == "#00FF00"
        # No blinking once the task is done — the border stays put.
        ks.advance_blink()
        assert ks.get_render_info()["border_color"] == "#00FF00"

    def test_failure_is_a_solid_red_border(self):
        ks = KeyState(task_cfg(), queue.Queue(maxsize=10))
        ks.press()
        ks.notify_state("failure")
        assert ks.get_render_info()["border_color"] == "#FF0000"

    def test_can_be_pressed_again_after_an_outcome(self):
        ks = KeyState(task_cfg(), queue.Queue(maxsize=10))
        ks.press()
        ks.notify_state("failure")
        state, action = ks.press()
        assert state == "running"
        assert action is not None

    def test_rejects_unknown_state(self):
        ks = KeyState(task_cfg(), queue.Queue(maxsize=10))
        ok, err = ks.notify_state("done")
        assert ok is False
        assert "invalid state 'done'" in err

    def test_outcome_is_not_persisted(self):
        """A finished flash must not restore a stale green border on boot."""
        from streamdeck_ctrl.key_manager import KeyManager

        km = KeyManager([task_cfg()], queue.Queue(maxsize=10))
        km.get_key((0, 0)).notify_state("success")
        assert km.get_persist_data() == {}

    def test_task_keys_are_listed(self):
        from streamdeck_ctrl.key_manager import KeyManager

        static = {
            "position": [0, 1],
            "label": "Static",
            "icon_type": "static",
            "icons": {"default": "/icons/x.png"},
        }
        km = KeyManager([task_cfg(), static], queue.Queue(maxsize=10))
        assert [ks.label for ks in km.task_keys()] == ["Flash"]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestBorderRendering:
    @pytest.fixture(autouse=True)
    def _clear_caches(self):
        clear_cache()
        yield
        clear_cache()

    def test_border_pixels_use_the_requested_color(self):
        img = render_bordered_image(GRAY, (72, 72), "#00FF00", 6)
        assert img.size == (72, 72)
        assert img.mode == "RGB"
        assert img.getpixel((0, 36)) == (0, 255, 0)
        assert img.getpixel((71, 36)) == (0, 255, 0)
        assert img.getpixel((36, 0)) == (0, 255, 0)
        assert img.getpixel((36, 71)) == (0, 255, 0)

    def test_border_leaves_the_icon_centre_alone(self):
        bare = render_bordered_image(GRAY, (72, 72), None, 6)
        bordered = render_bordered_image(GRAY, (72, 72), "#FF0000", 6)
        assert bordered.getpixel((36, 36)) == bare.getpixel((36, 36))

    def test_no_border_when_color_is_none(self):
        img = render_bordered_image(GRAY, (72, 72), None, 6)
        assert img.getpixel((0, 36)) == img.getpixel((36, 36))

    def test_no_border_when_width_is_zero(self):
        img = render_bordered_image(GRAY, (72, 72), "#00FF00", 0)
        assert img.getpixel((0, 36)) == img.getpixel((36, 36))


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


def write_config(tmpdir, keys, device=None):
    icons_dst = os.path.join(tmpdir, "icons")
    if not os.path.exists(icons_dst):
        os.symlink(FIXTURES, icons_dst)
    cfg = {
        "device": device or {"brightness": 75},
        "notification": {
            "type": "unix_socket",
            "socket_path": os.path.join(tmpdir, "notify.sock"),
            "state_persist_path": os.path.join(tmpdir, "state.json"),
        },
        "keys": keys,
    }
    path = os.path.join(tmpdir, "layout.json")
    with open(path, "w") as f:
        json.dump(cfg, f)
    return path


class TestTaskConfig:
    def test_defaults_are_injected(self, tmpdir):
        path = write_config(tmpdir, [{
            "position": [0, 0],
            "label": "Flash",
            "icon_type": "task",
            "icons": {"default": "icons/gray.png"},
            "notification_id": "test.flash",
        }])
        key = load_config(path)["keys"][0]
        assert key["initial_state"] == "idle"
        assert key["task"]["blink_interval_sec"] == 0.5
        assert key["task"]["border_width"] == 6
        assert key["task"]["colors"]["running"] == "#00FF00"
        assert key["task"]["colors"]["failure"] == "#FF0000"

    def test_explicit_colors_are_kept(self, tmpdir):
        path = write_config(tmpdir, [{
            "position": [0, 0],
            "label": "Flash",
            "icon_type": "task",
            "icons": {"default": "icons/gray.png"},
            "notification_id": "test.flash",
            "task": {"colors": {"success": "#0000FF"}},
        }])
        colors = load_config(path)["keys"][0]["task"]["colors"]
        assert colors["success"] == "#0000FF"
        assert colors["running"] == "#00FF00"  # still defaulted

    def test_notification_id_is_required(self, tmpdir):
        path = write_config(tmpdir, [{
            "position": [0, 0],
            "label": "Flash",
            "icon_type": "task",
            "icons": {"default": "icons/gray.png"},
        }])
        with pytest.raises(ValueError, match="task keys require notification_id"):
            load_config(path)

    def test_bad_color_is_rejected(self, tmpdir):
        path = write_config(tmpdir, [{
            "position": [0, 0],
            "label": "Flash",
            "icon_type": "task",
            "icons": {"default": "icons/gray.png"},
            "notification_id": "test.flash",
            "task": {"colors": {"running": "green"}},
        }])
        with pytest.raises(jsonschema.ValidationError):
            load_config(path)

    def test_display_control_config_is_valid(self):
        """The shipped screen must keep loading with the flash key added."""
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo, "screens", "display-control",
                            "display-control.json")
        cfg = load_config(path)
        flash = [k for k in cfg["keys"] if k["icon_type"] == "task"]
        assert len(flash) == 1
        assert flash[0]["notification_id"] == "ioc.flash_983hh"
        # It has to land on page 2 of a 15-key deck, behind the arrow.
        pages = PageManager(cfg["keys"], cfg["device"]["layout"])
        assert pages.page_count == 2
        assert flash[0] in pages._pages[1]


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestPhysicalPosLookup:
    def _keys(self, count):
        return [
            {
                "position": [i // 5, i % 5],
                "label": f"Key {i}",
                "icon_type": "static",
                "icons": {"default": "x.png"},
            }
            for i in range(count)
        ]

    def test_finds_a_key_on_the_current_page(self):
        pm = PageManager(self._keys(20), [3, 5])
        assert pm.get_physical_pos([0, 0]) == (0, 0)

    def test_key_on_another_page_is_not_found(self):
        pm = PageManager(self._keys(20), [3, 5])
        assert pm.get_physical_pos([3, 0]) is None  # 16th key, page 2

    def test_position_is_remapped_on_page_two(self):
        pm = PageManager(self._keys(20), [3, 5])
        pm.switch_page("right")
        # Page 2 keeps [2,0] for the back arrow, so the first key is at [0,0].
        assert pm.get_physical_pos([2, 4]) == (0, 0)
        assert pm.get_physical_pos([0, 0]) is None


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------


def _send_notification(sock_path, msg):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sock_path)
    s.settimeout(3.0)
    s.sendall(json.dumps(msg).encode() + b"\n")
    data = b""
    while b"\n" not in data:
        data += s.recv(4096)
    s.close()
    return json.loads(data.strip())


class TestTaskEndToEnd:
    @pytest.fixture
    def daemon(self, tmpdir):
        marker = os.path.join(tmpdir, "flashed")
        path = write_config(tmpdir, [{
            "position": [0, 0],
            "label": "Flash",
            "icon_type": "task",
            "icons": {"default": "icons/gray.png"},
            "notification_id": "test.flash",
            "task": {"blink_interval_sec": 0.05},
            "action": {"on_press": {
                "type": "script",
                "command": f"touch {marker}",
                "async": False,
            }},
        }])
        d = StreamDeckDaemon(config_path=path, simulate=True)
        t = threading.Thread(target=d.run, daemon=True)
        t.start()
        for _ in range(100):
            if os.path.exists(os.path.join(tmpdir, "notify.sock")):
                break
            time.sleep(0.01)
        time.sleep(0.2)  # let the render thread come up

        yield d, os.path.join(tmpdir, "notify.sock"), marker

        d._shutdown_event.set()
        t.join(timeout=5)

    def test_press_runs_the_script_and_blinks(self, daemon):
        d, _, marker = daemon
        d._deck.simulate_key_press(0, True)
        time.sleep(0.3)

        ks = d._key_manager.get_key((0, 0))
        assert ks.state == "running"
        assert os.path.exists(marker)

        # The blink thread keeps repainting the key while it runs.
        before = len(d._deck.image_updates)
        time.sleep(0.3)
        assert len(d._deck.image_updates) > before

    def test_success_notification_stops_the_blinking(self, daemon):
        d, sock_path, _ = daemon
        d._deck.simulate_key_press(0, True)
        time.sleep(0.2)

        assert _send_notification(sock_path, {"id": "test.flash",
                                              "state": "success"})["status"] == "ok"
        ks = d._key_manager.get_key((0, 0))
        assert ks.state == "success"
        assert ks.get_render_info()["border_color"] == "#00FF00"

        before = len(d._deck.image_updates)
        time.sleep(0.3)
        assert len(d._deck.image_updates) == before

    def test_press_on_page_two_redraws_at_once(self, tmpdir):
        """The border must appear on press, not on the next blink tick."""
        keys = [
            {
                "position": [i // 5, i % 5],
                "label": f"Key {i}",
                "icon_type": "static",
                "icons": {"default": "icons/blue.png"},
            }
            for i in range(20)
        ]
        keys.append({
            "position": [4, 0],
            "label": "Flash",
            "icon_type": "task",
            "icons": {"default": "icons/gray.png"},
            "notification_id": "test.flash",
            "task": {"blink_interval_sec": 30},  # far longer than this test
            "action": {"on_press": {"type": "script", "command": "true",
                                    "async": False}},
        })
        path = write_config(tmpdir, keys)
        shutil.copy(os.path.join(FIXTURES, "blue.png"),
                    os.path.join(tmpdir, "left-arrow.bmp"))
        shutil.copy(os.path.join(FIXTURES, "blue.png"),
                    os.path.join(tmpdir, "right-arrow.bmp"))

        d = StreamDeckDaemon(config_path=path, simulate=True)
        t = threading.Thread(target=d.run, daemon=True)
        t.start()
        try:
            for _ in range(100):
                if os.path.exists(os.path.join(tmpdir, "notify.sock")):
                    break
                time.sleep(0.01)
            time.sleep(0.3)

            # Bottom-right of a 3x5 deck is the "next page" arrow.
            d._deck.simulate_key_press(14, True)
            time.sleep(0.3)
            assert d._page_manager.current_page == 1

            slot = d._page_manager.get_physical_pos([4, 0])
            assert slot is not None
            before = len(d._deck.image_updates)
            d._deck.simulate_key_press(slot[0] * 5 + slot[1], True)
            time.sleep(0.2)

            ks = d._key_manager.get_key((4, 0))
            assert ks.state == "running"
            assert len(d._deck.image_updates) > before
        finally:
            d._shutdown_event.set()
            t.join(timeout=5)

    def test_failure_notification_leaves_a_red_border(self, daemon):
        d, sock_path, _ = daemon
        d._deck.simulate_key_press(0, True)
        time.sleep(0.2)

        _send_notification(sock_path, {"id": "test.flash", "state": "failure"})
        ks = d._key_manager.get_key((0, 0))
        assert ks.state == "failure"
        assert ks.get_render_info()["border_color"] == "#FF0000"
