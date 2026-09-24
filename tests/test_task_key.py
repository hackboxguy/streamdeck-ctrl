"""Tests for the `task` key type — blinking border, success/failure outcome."""

import json
import os
import queue
import re
import shutil
import socket
import tempfile
import threading
import time

import jsonschema
from PIL import Image
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
        assert [k["notification_id"] for k in flash] == [
            "ioc.flash_983hh", "ioc.flash_spartan7", "ioc.flash_lat45",
            "ioc.flash_oled_ots", "fpga.flash_12_3_nq5",
            "fpga.flash_15_6_0od",
        ]

        # Three IOC keys sit on page 2's bottom row beside the back arrow;
        # the deck's own "next page" arrow takes the last slot of that row,
        # pushing the remaining two onto page 3. Their placement rides on the
        # filler "Blank" keys ahead of them, so a key inserted before them
        # would shift the lot.
        pages = PageManager(cfg["keys"], cfg["device"]["layout"])
        assert pages.page_count == 3
        pages.switch_page("right")
        assert pages._left_arrow_pos == (2, 0)
        assert pages.is_nav_key((2, 4)) == "right"
        assert [pages.get_physical_pos(k["position"]) for k in flash[:3]] == [
            (2, 1), (2, 2), (2, 3)]

        pages.switch_page("right")
        assert [pages.get_physical_pos(k["position"]) for k in flash[3:]] == [
            (0, 0), (0, 1), (0, 2)]

    def test_every_flash_key_drives_a_shared_script(self):
        """Each target differs only by its arguments, never by its script."""
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(repo, "screens", "display-control",
                            "display-control.json")
        cfg = load_config(path)
        flash = [k for k in cfg["keys"] if k["icon_type"] == "task"]

        boards = set()
        for k in flash:
            cmd = k["action"]["on_press"]["command"]
            # The id the script reports on must be the key's own, whichever
            # script it is -- a copy-pasted id would light up a sibling key.
            assert f"--id={k['notification_id']} " in cmd

            if k["notification_id"].startswith("fpga."):
                assert "scripts/flash-fpga.sh " in cmd
                assert "--file=" in cmd
                assert cmd.split("--fpga-type=")[1].split()[0] in (
                    "xilinx", "lattice")
                continue

            assert "scripts/flash-ioc.sh " in cmd
            assert "--firmware=" in cmd
            board = cmd.split("--board=")[1].split()[0]
            boards.add(board)
            # spartan7-9090 is driven without an npj; the rest need one.
            assert ("--npj=" in cmd) == (board != "spartan7-9090")
        assert boards == {"983hh", "spartan7-9090", "lattice45-9090"}

    def test_flash_scripts_share_one_board_lock(self):
        """JTAG and Bluebox runs drive the same board; never both at once."""
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        scripts = os.path.join(repo, "screens", "display-control", "scripts")
        locks = set()
        for name in ("flash-ioc.sh", "flash-fpga.sh"):
            body = open(os.path.join(scripts, name)).read()
            locks.add(re.search(r'LOCK_FILE="([^"]+)"', body).group(1))
        assert len(locks) == 1, f"flash scripts use different locks: {locks}"


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


class TestHdmiRadioKeys:
    """The timing radios and the sync script must agree on notification ids.

    sync-hdmi-timing.sh pushes one notification per timing profile so exactly
    one radio lights up. An id in the config with no line in that map is a key
    that can never turn on; a line with no key is a notification the daemon
    rejects. Neither shows up until someone watches the deck, so pin it here.
    """

    def _config(self):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(repo, "screens", "display-control",
                            "display-control.json"), repo

    def test_every_hdmi_radio_is_in_the_sync_map(self):
        path, repo = self._config()
        cfg = load_config(path)
        # radio keys are also used outside HDMI selection (e.g. demo.* clip keys)
        keys = {k["notification_id"] for k in cfg["keys"]
                if k["icon_type"] == "radio" and k["notification_id"].startswith("hdmi.")}

        sync = open(os.path.join(repo, "screens", "display-control", "scripts",
                                 "sync-hdmi-timing.sh")).read()
        mapped = set(re.findall(r'\["[^"]+"\]="(hdmi\.[a-z0-9_]+)"', sync))

        assert keys == mapped, (
            f"config-only: {sorted(keys - mapped)}, "
            f"sync-only: {sorted(mapped - keys)}"
        )

    def test_each_radio_applies_its_own_timing(self):
        """Two radios sharing an apply script would be a copy-paste slip."""
        path, _ = self._config()
        cfg = load_config(path)
        commands = [k["action"]["on_press"]["command"]
                    for k in cfg["keys"] if k["icon_type"] == "radio"]
        assert len(commands) == len(set(commands))

    def test_qvue_sits_beside_the_ots_oled_key(self):
        path, _ = self._config()
        cfg = load_config(path)
        pages = PageManager(cfg["keys"], cfg["device"]["layout"])
        pages.switch_page("right")
        pos = {k["label"]: pages.get_physical_pos(k["position"])
               for k in cfg["keys"]}
        ots, qvue = pos["HDMI 17.3-OTS-OLED"], pos["HDMI 3x-QVue"]
        assert ots is not None and qvue == (ots[0], ots[1] + 1)


class TestTextWrapping:
    """Overflowing live_value text wraps instead of clipping off both edges."""

    def _font_and_draw(self, size=13):
        from PIL import ImageDraw, ImageFont
        from streamdeck_ctrl.icon_renderer import _DEFAULT_FONT_PATH
        return (ImageFont.truetype(_DEFAULT_FONT_PATH, size),
                ImageDraw.Draw(Image.new("RGB", (72, 72))))

    def test_short_values_are_left_alone(self):
        """A temperature or percentage must not gain a line break."""
        from streamdeck_ctrl.icon_renderer import _wrap_to_width
        font, draw = self._font_and_draw()
        for value in ("53.2", "80%", "No IP!", "10.0.0.5"):
            assert _wrap_to_width(value, font, draw, 64) == [value]

    def test_an_ip_breaks_after_a_dot(self):
        from streamdeck_ctrl.icon_renderer import _wrap_to_width
        font, draw = self._font_and_draw()
        assert _wrap_to_width("192.168.1.167", font, draw, 64) == [
            "192.168.", "1.167"]
        assert _wrap_to_width("255.255.255.255", font, draw, 64) == [
            "255.255.", "255.255"]

    def test_every_line_fits_the_key(self):
        from streamdeck_ctrl.icon_renderer import _wrap_to_width
        font, draw = self._font_and_draw()
        for value in ("192.168.100.100", "255.255.255.255", "10.11.12.13"):
            for line in _wrap_to_width(value, font, draw, 64):
                assert draw.textbbox((0, 0), line, font=font)[2] <= 64

    def test_a_single_unbreakable_word_is_hard_broken(self):
        """No separator to break on, but it still must not run off the key."""
        from streamdeck_ctrl.icon_renderer import _wrap_to_width
        font, draw = self._font_and_draw()
        lines = _wrap_to_width("ABCDEFGHIJKLMNOPQRST", font, draw, 64)
        assert len(lines) > 1
        for line in lines:
            assert draw.textbbox((0, 0), line, font=font)[2] <= 64

    def test_rendered_ip_stays_inside_the_key(self):
        """The regression this fixes: text clipped at x=0 and x=71."""
        from streamdeck_ctrl.icon_renderer import render_live_value_image
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        base = os.path.join(repo, "screens", "display-control", "ip-address.png")
        img = render_live_value_image(base, (72, 72), "192.168.1.167",
                                      "#FFFFFF", 13, None, "bottom")
        px = img.load()
        lit = [x for x in range(72)
               if any(min(px[x, y]) > 200 for y in range(72))]
        assert min(lit) > 0 and max(lit) < 71


class TestIpKey:
    def test_ip_key_is_a_passive_live_value(self):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg = load_config(os.path.join(repo, "screens", "display-control",
                                       "display-control.json"))
        ip = [k for k in cfg["keys"]
              if k.get("notification_id") == "system.ip"]
        assert len(ip) == 1
        ip = ip[0]
        assert ip["icon_type"] == "live_value"
        # Pressing it must do nothing at all.
        assert ip.get("action") is None
        # Polled *and* notifiable: the dispatcher hook is an optimisation, so
        # the value must still refresh if that hook is never installed.
        assert ip["live"]["source"] == "poll+notify"
        assert os.path.isfile(ip["live"]["poll_command"].replace(
            "{INSTALL_DIR}", repo))

    def test_ip_key_sits_below_display_settings(self):
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg = load_config(os.path.join(repo, "screens", "display-control",
                                       "display-control.json"))
        pages = PageManager(cfg["keys"], cfg["device"]["layout"])
        pos = {k["label"]: pages.get_physical_pos(k["position"])
               for k in cfg["keys"]}
        settings, ip = pos["Display Settings"], pos["IP Address"]
        assert settings is not None
        assert ip == (settings[0] + 1, settings[1])
