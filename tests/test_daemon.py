"""Tests for streamdeck_ctrl.daemon — FakeDeck, simulate mode, dry_run."""

import json
import os
import queue
import shutil
import socket
import tempfile
import threading
import time

import pytest

from streamdeck_ctrl.daemon import FakeDeck, StreamDeckDaemon, dry_run


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "icons")


def _write_test_config(tmpdir, extra_keys=None):
    """Write a minimal valid config with real icon files."""
    keys = extra_keys or [
        {
            "position": [0, 0],
            "label": "Toggle1",
            "icon_type": "toggle",
            "icons": {"on": "icons/green.png", "off": "icons/red.png"},
            "initial_state": "off",
            "notification_id": "test.toggle",
            "action": {"on_press": {"type": "script", "command": "echo {state}", "async": False}},
        },
        {
            "position": [0, 1],
            "label": "Static1",
            "icon_type": "static",
            "icons": {"default": "icons/blue.png"},
        },
        {
            "position": [1, 0],
            "label": "Live1",
            "icon_type": "live_value",
            "icons": {"base": "icons/gray.png"},
            "live": {"source": "notify_only", "format": "{value}%"},
            "notification_id": "test.live",
        },
    ]
    cfg = {
        "device": {"brightness": 50},
        "notification": {
            "type": "unix_socket",
            "socket_path": os.path.join(tmpdir, "notify.sock"),
            "state_persist_path": os.path.join(tmpdir, "state.json"),
        },
        "keys": keys,
    }
    # Link icons
    icons_dst = os.path.join(tmpdir, "icons")
    if not os.path.exists(icons_dst):
        os.symlink(FIXTURES, icons_dst)
    config_path = os.path.join(tmpdir, "layout.json")
    with open(config_path, "w") as f:
        json.dump(cfg, f)
    return config_path


@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


# ---------------------------------------------------------------------------
# FakeDeck
# ---------------------------------------------------------------------------


class TestFakeDeck:
    def test_key_count(self):
        deck = FakeDeck()
        assert deck.key_count() == 15

    def test_key_image_format(self):
        deck = FakeDeck()
        fmt = deck.key_image_format()
        assert fmt["size"] == (72, 72)

    def test_set_brightness(self):
        deck = FakeDeck()
        deck.set_brightness(80)  # should not raise

    def test_set_key_image_recorded(self):
        deck = FakeDeck()
        deck.set_key_image(0, b"fake_image_data")
        assert len(deck.image_updates) == 1
        assert deck.image_updates[0] == (0, 15)

    def test_simulate_key_press(self):
        deck = FakeDeck()
        presses = []
        deck.set_key_callback(lambda d, k, p: presses.append((k, p)))
        deck.simulate_key_press(3, True)
        assert presses == [(3, True)]

    def test_reset_and_close(self):
        deck = FakeDeck()
        deck.reset()
        deck.close()
        assert deck.is_open()  # FakeDeck stays "open"


# ---------------------------------------------------------------------------
# StreamDeckDaemon in simulate mode
# ---------------------------------------------------------------------------


class TestSimulateMode:
    def test_simulate_starts_and_stops(self, tmpdir):
        config_path = _write_test_config(tmpdir)
        daemon = StreamDeckDaemon(
            config_path=config_path,
            simulate=True,
        )

        # Run in a thread, stop after brief delay
        def run_daemon():
            daemon.run()

        t = threading.Thread(target=run_daemon)
        t.start()
        time.sleep(0.5)
        daemon._shutdown_event.set()
        t.join(timeout=5)
        assert not t.is_alive()

    def test_simulate_processes_notifications(self, tmpdir):
        config_path = _write_test_config(tmpdir)
        sock_path = os.path.join(tmpdir, "notify.sock")
        daemon = StreamDeckDaemon(
            config_path=config_path,
            simulate=True,
        )

        t = threading.Thread(target=daemon.run)
        t.start()

        # Wait for socket to be ready
        for _ in range(100):
            if os.path.exists(sock_path):
                break
            time.sleep(0.01)

        # Send notification
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(sock_path)
        s.settimeout(2.0)
        s.sendall(json.dumps({"id": "test.toggle", "state": "on"}).encode() + b"\n")
        resp = b""
        while b"\n" not in resp:
            resp += s.recv(4096)
        s.close()

        result = json.loads(resp.strip())
        assert result["status"] == "ok"

        # Verify state was persisted
        time.sleep(0.2)
        persist_path = os.path.join(tmpdir, "state.json")
        with open(persist_path) as f:
            persisted = json.load(f)
        assert persisted["test.toggle"]["state"] == "on"

        daemon._shutdown_event.set()
        t.join(timeout=5)

    def test_simulate_key_press_fires_action(self, tmpdir):
        config_path = _write_test_config(tmpdir)
        daemon = StreamDeckDaemon(
            config_path=config_path,
            simulate=True,
        )

        t = threading.Thread(target=daemon.run)
        t.start()
        time.sleep(0.5)

        # Simulate key press on toggle key (position 0,0 = key index 0)
        if daemon._deck:
            daemon._deck.simulate_key_press(0, True)
            time.sleep(0.2)
            # Check state changed
            ks = daemon._key_manager.get_key((0, 0))
            assert ks.state == "on"

        daemon._shutdown_event.set()
        t.join(timeout=5)


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_dry_run_output(self, tmpdir, capsys):
        config_path = _write_test_config(tmpdir)
        dry_run(config_path)
        output = capsys.readouterr().out
        assert "[DRY RUN]" in output
        assert "Toggle1" in output
        assert "Static1" in output
        assert "Live1" in output
        assert "All icon files resolved" in output

    def test_dry_run_missing_icon(self, tmpdir):
        keys = [
            {
                "position": [0, 0],
                "label": "Bad",
                "icon_type": "static",
                "icons": {"default": "icons/nonexistent.png"},
            }
        ]
        config_path = _write_test_config(tmpdir, extra_keys=keys)
        with pytest.raises(FileNotFoundError):
            dry_run(config_path)
