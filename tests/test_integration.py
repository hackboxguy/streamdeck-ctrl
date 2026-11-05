"""Integration test: full stack with simulate mode, socket notifications, key presses."""

import json
import os
import shutil
import socket
import tempfile
import threading
import time

import pytest

from streamdeck_ctrl.daemon import StreamDeckDaemon


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "icons")


def _write_full_config(tmpdir):
    """Write a config with all 4 key types using real test icons."""
    icons_dst = os.path.join(tmpdir, "icons")
    if not os.path.exists(icons_dst):
        os.symlink(FIXTURES, icons_dst)

    cfg = {
        "device": {"brightness": 75},
        "notification": {
            "type": "unix_socket",
            "socket_path": os.path.join(tmpdir, "notify.sock"),
            "state_persist_path": os.path.join(tmpdir, "state.json"),
        },
        "keys": [
            {
                "position": [0, 0],
                "label": "Backlight",
                "icon_type": "toggle",
                "icons": {"on": "icons/green.png", "off": "icons/red.png"},
                "initial_state": "off",
                "notification_id": "backlight.state",
                "action": {"on_press": {"type": "script", "command": "echo {state}", "async": False}},
            },
            {
                "position": [0, 1],
                "label": "Reboot",
                "icon_type": "static",
                "icons": {"default": "icons/blue.png"},
                "action": {"on_press": {"type": "script", "command": "echo reboot", "async": False}},
            },
            {
                "position": [0, 2],
                "label": "Display Mode",
                "icon_type": "multistate",
                "states": ["sdr", "hdr", "night"],
                "icons": {"sdr": "icons/red.png", "hdr": "icons/green.png", "night": "icons/blue.png"},
                "initial_state": "sdr",
                "notification_id": "display.mode",
                "action": {"on_press": {"type": "script", "command": "echo {state}", "async": False}},
            },
            {
                "position": [1, 0],
                "label": "CPU Temp",
                "icon_type": "live_value",
                "icons": {"base": "icons/gray.png"},
                "live": {
                    "source": "notify_only",
                    "format": "{value}°C",
                    "text_anchor": "bottom",
                    "text_color": "#FFFFFF",
                    "font_size": 14,
                },
                "notification_id": "sensor.temp",
            },
        ],
    }
    path = os.path.join(tmpdir, "layout.json")
    with open(path, "w") as f:
        json.dump(cfg, f)
    return path


def _send_notification(sock_path, msg):
    """Send a single notification and return the response."""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sock_path)
    s.settimeout(3.0)
    s.sendall(json.dumps(msg).encode() + b"\n")
    data = b""
    while b"\n" not in data:
        data += s.recv(4096)
    s.close()
    return json.loads(data.strip())


@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def running_daemon(tmpdir):
    """Start a daemon in simulate mode, yield it, then shut down."""
    config_path = _write_full_config(tmpdir)
    sock_path = os.path.join(tmpdir, "notify.sock")

    daemon = StreamDeckDaemon(config_path=config_path, simulate=True)
    t = threading.Thread(target=daemon.run, daemon=True)
    t.start()

    # Wait for socket
    for _ in range(100):
        if os.path.exists(sock_path):
            break
        time.sleep(0.01)

    yield daemon, sock_path, tmpdir

    daemon._shutdown_event.set()
    t.join(timeout=5)


class TestIntegration:
    def test_toggle_via_notification(self, running_daemon):
        daemon, sock_path, tmpdir = running_daemon

        # Set toggle to on via notification
        resp = _send_notification(sock_path, {"id": "backlight.state", "state": "on"})
        assert resp["status"] == "ok"

        # Verify key state
        ks = daemon._key_manager.get_key_by_notification_id("backlight.state")
        assert ks.state == "on"

        # Verify persisted
        time.sleep(0.1)
        with open(os.path.join(tmpdir, "state.json")) as f:
            persisted = json.load(f)
        assert persisted["backlight.state"]["state"] == "on"

    def test_multistate_via_notification(self, running_daemon):
        daemon, sock_path, _ = running_daemon

        resp = _send_notification(sock_path, {"id": "display.mode", "state": "hdr"})
        assert resp["status"] == "ok"

        ks = daemon._key_manager.get_key_by_notification_id("display.mode")
        assert ks.state == "hdr"

    def test_multistate_invalid_state(self, running_daemon):
        _, sock_path, _ = running_daemon

        resp = _send_notification(sock_path, {"id": "display.mode", "state": "invalid"})
        assert resp["status"] == "error"
        assert "invalid state" in resp["reason"]

    def test_live_value_via_notification(self, running_daemon):
        daemon, sock_path, _ = running_daemon

        resp = _send_notification(sock_path, {"id": "sensor.temp", "value": "53.2"})
        assert resp["status"] == "ok"

        ks = daemon._key_manager.get_key_by_notification_id("sensor.temp")
        assert ks.value == "53.2"

    def test_unknown_notification_id(self, running_daemon):
        _, sock_path, _ = running_daemon

        resp = _send_notification(sock_path, {"id": "nonexistent.key", "state": "on"})
        assert resp["status"] == "error"
        assert "unknown" in resp["reason"]

    def test_key_press_toggle(self, running_daemon):
        daemon, _, _ = running_daemon
        time.sleep(0.3)  # let render thread start

        # Simulate key press on toggle (position 0,0 = key index 0)
        daemon._deck.simulate_key_press(0, True)
        time.sleep(0.2)

        ks = daemon._key_manager.get_key((0, 0))
        assert ks.state == "on"

        # Press again
        daemon._deck.simulate_key_press(0, True)
        time.sleep(0.2)
        assert ks.state == "off"

    def test_key_press_multistate_cycles(self, running_daemon):
        daemon, _, _ = running_daemon
        time.sleep(0.3)

        ks = daemon._key_manager.get_key((0, 2))
        assert ks.state == "sdr"

        # key index for position (0,2) = 0*5+2 = 2
        daemon._deck.simulate_key_press(2, True)
        time.sleep(0.2)
        assert ks.state == "hdr"

        daemon._deck.simulate_key_press(2, True)
        time.sleep(0.2)
        assert ks.state == "night"

        daemon._deck.simulate_key_press(2, True)
        time.sleep(0.2)
        assert ks.state == "sdr"  # wrapped

    def test_multiple_notifications_one_connection(self, running_daemon):
        daemon, sock_path, _ = running_daemon

        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(sock_path)
        s.settimeout(3.0)

        # Send multiple messages
        msgs = [
            {"id": "backlight.state", "state": "on"},
            {"id": "display.mode", "state": "night"},
            {"id": "sensor.temp", "value": "61.3"},
        ]
        responses = []
        for msg in msgs:
            s.sendall(json.dumps(msg).encode() + b"\n")
            data = b""
            while b"\n" not in data:
                data += s.recv(4096)
            responses.append(json.loads(data.strip()))
        s.close()

        assert all(r["status"] == "ok" for r in responses)
        assert daemon._key_manager.get_key_by_notification_id("backlight.state").state == "on"
        assert daemon._key_manager.get_key_by_notification_id("display.mode").state == "night"
        assert daemon._key_manager.get_key_by_notification_id("sensor.temp").value == "61.3"

    def test_state_persistence_survives_restart(self, tmpdir):
        """State persisted by first daemon instance is restored by second."""
        config_path = _write_full_config(tmpdir)
        sock_path = os.path.join(tmpdir, "notify.sock")

        # First instance: set some state
        d1 = StreamDeckDaemon(config_path=config_path, simulate=True)
        t1 = threading.Thread(target=d1.run, daemon=True)
        t1.start()
        for _ in range(100):
            if os.path.exists(sock_path):
                break
            time.sleep(0.01)

        _send_notification(sock_path, {"id": "backlight.state", "state": "on"})
        _send_notification(sock_path, {"id": "display.mode", "state": "night"})
        time.sleep(0.2)
        d1._shutdown_event.set()
        t1.join(timeout=5)

        # Second instance: should restore state
        d2 = StreamDeckDaemon(config_path=config_path, simulate=True)
        t2 = threading.Thread(target=d2.run, daemon=True)
        t2.start()
        for _ in range(100):
            if os.path.exists(sock_path):
                break
            time.sleep(0.01)
        time.sleep(0.3)

        assert d2._key_manager.get_key_by_notification_id("backlight.state").state == "on"
        assert d2._key_manager.get_key_by_notification_id("display.mode").state == "night"

        d2._shutdown_event.set()
        t2.join(timeout=5)

    def test_render_queue_processes_updates(self, running_daemon):
        daemon, sock_path, _ = running_daemon
        time.sleep(0.3)  # let initial renders process

        # Record image updates before
        initial_count = len(daemon._deck.image_updates)

        # Send notification that triggers re-render
        _send_notification(sock_path, {"id": "backlight.state", "state": "on"})
        time.sleep(0.3)

        # Should have more image updates now
        assert len(daemon._deck.image_updates) > initial_count


class TestPressAndHold:
    def _daemon(self, tmpdir, hold=0.3):
        icons_dst = os.path.join(tmpdir, "icons")
        if not os.path.exists(icons_dst):
            os.symlink(FIXTURES, icons_dst)
        marker = os.path.join(tmpdir, "pressed")
        cfg = {
            "device": {"brightness": 75},
            "notification": {"type": "unix_socket",
                             "socket_path": os.path.join(tmpdir, "notify.sock"),
                             "state_persist_path": os.path.join(tmpdir, "state.json")},
            "keys": [{
                "position": [0, 0], "label": "OTA", "icon_type": "task",
                "icons": {"default": "icons/blue.png"}, "notification_id": "ota.ioc",
                "initial_state": "available",
                "task": {"hold_sec": hold, "press_states": ["available"],
                         "grey_states": ["idle"],
                         "colors": {"available": "#FFD000", "running": "#00FF00"}},
                "action": {"on_press": {"type": "script",
                                        "command": f"touch {marker}", "async": False}},
            }],
        }
        path = os.path.join(tmpdir, "layout.json")
        with open(path, "w") as f:
            json.dump(cfg, f)
        daemon = StreamDeckDaemon(config_path=path, simulate=True)
        t = threading.Thread(target=daemon.run, daemon=True)
        t.start()
        for _ in range(200):
            if daemon._deck is not None:
                break
            time.sleep(0.01)
        return daemon, marker

    def test_released_early_does_nothing(self, tmpdir):
        daemon, marker = self._daemon(tmpdir)
        try:
            daemon._deck.simulate_key_press(0, True)
            time.sleep(0.1)
            daemon._deck.simulate_key_press(0, False)
            time.sleep(0.5)
            assert not os.path.exists(marker)
            assert daemon._key_manager.get_key((0, 0)).state == "available"
        finally:
            daemon._shutdown_event.set()

    def test_held_long_enough_presses(self, tmpdir):
        daemon, marker = self._daemon(tmpdir)
        try:
            daemon._deck.simulate_key_press(0, True)
            time.sleep(0.6)
            daemon._deck.simulate_key_press(0, False)
            for _ in range(100):
                if os.path.exists(marker):
                    break
                time.sleep(0.02)
            assert os.path.exists(marker)
            assert daemon._key_manager.get_key((0, 0)).state == "running"
        finally:
            daemon._shutdown_event.set()


class TestNotificationBurstWithPagination:
    def test_burst_neither_raises_nor_redraws_the_page(self, tmpdir):
        """A job's progress stream on a paginated deck: each notification
        redraws its own key only, and a full render queue never surfaces as
        an exception (it used to kill the notifier)."""
        icons_dst = os.path.join(tmpdir, "icons")
        if not os.path.exists(icons_dst):
            os.symlink(FIXTURES, icons_dst)
        keys = [{"position": [i // 5, i % 5], "label": f"K{i}", "icon_type": "static",
                 "icons": {"default": "icons/blue.png"}} for i in range(20)]
        keys[1] = {"position": [0, 1], "label": "Job", "icon_type": "task",
                   "icons": {"default": "icons/blue.png"}, "notification_id": "job"}
        cfg = {"device": {"brightness": 75},
               "notification": {"type": "unix_socket",
                                "socket_path": os.path.join(tmpdir, "notify.sock"),
                                "state_persist_path": os.path.join(tmpdir, "state.json")},
               "keys": keys}
        path = os.path.join(tmpdir, "layout.json")
        with open(path, "w") as f:
            json.dump(cfg, f)
        daemon = StreamDeckDaemon(config_path=path, simulate=True)
        t = threading.Thread(target=daemon.run, daemon=True)
        t.start()
        try:
            for _ in range(200):
                if daemon._deck is not None and daemon._page_manager is not None:
                    break
                time.sleep(0.01)
            time.sleep(0.3)
            # One notification redraws one key, not the page
            while not daemon._render_queue.empty():
                time.sleep(0.01)
            q_before = daemon._render_queue.qsize()
            ok, _ = daemon._handle_notification("job", state="running", value="10")
            assert ok
            assert daemon._render_queue.qsize() - q_before <= 2
            # A burst far beyond the queue's size never raises
            for i in range(2000):
                ok, err = daemon._handle_notification("job", value=str(i % 100))
                assert ok, err
        finally:
            daemon._shutdown_event.set()
