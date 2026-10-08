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

    def test_state_watch_synchronizes_toggle(self, tmpdir):
        shared_state_path = os.path.join(tmpdir, "fpga-ldpc-state.json")
        with open(shared_state_path, "w") as state_file:
            json.dump({"local_dimming": True}, state_file)

        keys = [
            {
                "position": [0, 0],
                "label": "Local Dimming",
                "icon_type": "toggle",
                "icons": {"on": "icons/green.png", "off": "icons/red.png"},
                "initial_state": "off",
                "notification_id": "display.local_dimming",
                "state_watch": {
                    "path": shared_state_path,
                    "json_key": "local_dimming",
                    "poll_interval_sec": 1,
                    "default_state": "on",
                },
            }
        ]
        config_path = _write_test_config(tmpdir, extra_keys=keys)
        daemon = StreamDeckDaemon(config_path=config_path, simulate=True)
        thread = threading.Thread(target=daemon.run)
        thread.start()

        for _ in range(100):
            if daemon._key_manager:
                key = daemon._key_manager.get_key((0, 0))
                if key and key.state == "on":
                    break
            time.sleep(0.02)
        assert daemon._key_manager.get_key((0, 0)).state == "on"

        with open(shared_state_path, "w") as state_file:
            json.dump({"local_dimming": False}, state_file)

        for _ in range(100):
            if daemon._key_manager.get_key((0, 0)).state == "off":
                break
            time.sleep(0.02)
        assert daemon._key_manager.get_key((0, 0)).state == "off"

        daemon._shutdown_event.set()
        thread.join(timeout=5)


    @staticmethod
    def _wait_state(daemon, pos, state):
        for _ in range(200):
            if daemon._key_manager:
                key = daemon._key_manager.get_key(pos)
                if key and key.state == state:
                    return True
            time.sleep(0.02)
        return False

    def test_state_watch_text_file_with_map(self, tmpdir):
        # The cluster's dms-video-view.state: on/off/none, the DMS key on unless "none"
        state_path = os.path.join(tmpdir, "dms-video-view.state")
        with open(state_path, "w") as f:
            f.write("on\n")
        keys = [{
            "position": [0, 0], "label": "DMS", "icon_type": "toggle",
            "icons": {"on": "icons/green.png", "off": "icons/red.png"},
            "initial_state": "off", "notification_id": "cluster.dms",
            "state_watch": {"path": [os.path.join(tmpdir, "nodir", "x.state"), state_path],
                            "text_map": {"none": "off", "*": "on"}, "default_state": "on"},
        }]
        daemon = StreamDeckDaemon(config_path=_write_test_config(tmpdir, extra_keys=keys), simulate=True)
        thread = threading.Thread(target=daemon.run)
        thread.start()
        try:
            assert self._wait_state(daemon, (0, 0), "on")
            with open(state_path + ".new", "w") as f:
                f.write("none\n")
            os.replace(state_path + ".new", state_path)
            assert self._wait_state(daemon, (0, 0), "off")
            with open(state_path, "w") as f:
                f.write("off\n")      # camera off: the panel still there
            assert self._wait_state(daemon, (0, 0), "on")
        finally:
            daemon._shutdown_event.set()
            thread.join(timeout=5)

    def test_state_watch_command_shared_by_radios(self, tmpdir):
        # The launcher's running app lights one theme radio; one command for both keys
        app_path = os.path.join(tmpdir, "running")
        count_path = os.path.join(tmpdir, "count")
        with open(app_path, "w") as f:
            f.write("cluster-v2-ev\n")
        command = f"echo x >> {count_path}; cat {app_path}"
        keys = [
            {"position": [0, 0], "label": "EV", "icon_type": "radio",
             "icons": {"on": "icons/green.png", "off": "icons/red.png"},
             "initial_state": "off", "notification_id": "cluster.theme_ev",
             "state_watch": {"command": command, "text_map": {"cluster-v2-ev": "on", "*": "off"}}},
            {"position": [0, 1], "label": "Neo", "icon_type": "radio",
             "icons": {"on": "icons/green.png", "off": "icons/red.png"},
             "initial_state": "off", "notification_id": "cluster.theme_neo",
             "state_watch": {"command": command, "text_map": {"cluster-v2-neo": "on", "*": "off"}}},
        ]
        daemon = StreamDeckDaemon(config_path=_write_test_config(tmpdir, extra_keys=keys), simulate=True)
        thread = threading.Thread(target=daemon.run)
        thread.start()
        try:
            assert self._wait_state(daemon, (0, 0), "on")
            assert daemon._key_manager.get_key((0, 1)).state == "off"
            with open(app_path, "w") as f:
                f.write("cluster-v2-neo\n")
            assert self._wait_state(daemon, (0, 1), "on")
            assert self._wait_state(daemon, (0, 0), "off")
            time.sleep(1.2)
            with open(count_path) as f:
                runs = len(f.readlines())
            start_runs = runs
            time.sleep(2.2)
            with open(count_path) as f:
                runs = len(f.readlines())
            # one poller for both keys: about one run a second, not two
            assert runs - start_runs <= 3
        finally:
            daemon._shutdown_event.set()
            thread.join(timeout=5)

    def test_state_watch_drives_a_task_key(self, tmpdir):
        word_path = os.path.join(tmpdir, "word")
        with open(word_path, "w") as f:
            f.write("other\n")
        keys = [{"position": [0, 0], "label": "Link", "icon_type": "task",
                 "icons": {"default": "icons/gray.png"}, "notification_id": "test.link",
                 "state_watch": {"command": f"cat {word_path}",
                                 "text_map": {"serving": "success", "stopped": "failure", "*": "idle"}}}]
        daemon = StreamDeckDaemon(config_path=_write_test_config(tmpdir, extra_keys=keys), simulate=True)
        thread = threading.Thread(target=daemon.run)
        thread.start()
        try:
            assert self._wait_state(daemon, (0, 0), "idle")
            with open(word_path, "w") as f:
                f.write("serving\n")
            assert self._wait_state(daemon, (0, 0), "success")
            with open(word_path, "w") as f:
                f.write("stopped\n")
            assert self._wait_state(daemon, (0, 0), "failure")
        finally:
            daemon._shutdown_event.set()
            thread.join(timeout=5)

    def test_state_watch_unknown_word_is_ignored(self):
        warned = set()
        watch = {"text_map": {"on": "on", "off": "off"}}
        assert StreamDeckDaemon._watch_state(watch, ("text", "sideways\n"), warned) is None
        assert "sideways" in warned
        assert StreamDeckDaemon._watch_state(watch, ("text", "off"), warned) == "off"
        assert StreamDeckDaemon._watch_state(watch, ("missing",), warned) == "off"
        assert StreamDeckDaemon._watch_state({"text_map": {"on": "on"}, "default_state": "on"},
                                             ("missing",), warned) == "on"
        assert StreamDeckDaemon._watch_state(watch, None, warned) is None

    def test_state_watch_path_candidates(self, tmpdir):
        present = os.path.join(tmpdir, "f.json")
        absent = os.path.join(tmpdir, "no", "such", "f.json")
        assert StreamDeckDaemon._watch_path([absent, present]) == present
        assert StreamDeckDaemon._watch_path([present, absent]) == present
        assert StreamDeckDaemon._watch_path([absent]) == absent



class TestPagedRedraws:
    """A key's own redraw lands in its slot on the current page, or nowhere."""

    @staticmethod
    def _paged(tmpdir):
        keys = [{"position": [10 + i // 5, i % 5], "label": f"K{i}", "icon_type": "toggle",
                 "icons": {"on": "icons/green.png", "off": "icons/red.png"},
                 "initial_state": "off", "notification_id": f"test.k{i}"} for i in range(20)]
        daemon = StreamDeckDaemon(config_path=_write_test_config(tmpdir, extra_keys=keys), simulate=True)
        from streamdeck_ctrl.page_manager import PageManager
        daemon._page_manager = PageManager(keys, (3, 5))
        from streamdeck_ctrl.daemon import _PageRenderQueue
        return daemon, keys, _PageRenderQueue(daemon)

    def test_redraw_is_mapped_to_the_slot(self, tmpdir):
        daemon, keys, proxy = self._paged(tmpdir)
        proxy.put_nowait({"position": (10, 2), "icon_type": "toggle", "icon_path": "x"})
        job = daemon._render_queue.get_nowait()
        assert job["position"] == (0, 2) and job["logical"] == (10, 2)
        assert daemon._render_job_current(job)

    def test_redraw_of_a_key_on_another_page_is_dropped(self, tmpdir):
        daemon, keys, proxy = self._paged(tmpdir)
        proxy.put_nowait({"position": (13, 0), "icon_type": "toggle", "icon_path": "x"})  # page 2
        assert daemon._render_queue.empty()

    def test_a_stale_job_does_not_draw_into_another_key(self, tmpdir):
        daemon, keys, proxy = self._paged(tmpdir)
        proxy.put_nowait({"position": (10, 1), "icon_type": "toggle", "icon_path": "x"})
        job = daemon._render_queue.get_nowait()
        daemon._page_manager.switch_page("right")      # slot (0, 1) now holds another key
        assert not daemon._render_job_current(job)
        # nor a job still at a key's logical position that happens to be a slot
        assert not daemon._render_job_current({"position": (0, 1), "icon_type": "toggle"})
        assert daemon._render_job_current({"position": (0, 1), "icon_type": "__blank__"})


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
