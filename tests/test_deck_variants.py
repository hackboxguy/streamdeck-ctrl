"""Per-deck config variants: <stem>-<cols>x<rows>.json is chosen for a deck of that size."""

import json
import os
import shutil
import tempfile
import threading
import time

import pytest

from streamdeck_ctrl.config import config_for_layout, load_config
from streamdeck_ctrl.daemon import FakeDeck, StreamDeckDaemon

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "icons")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREEN = os.path.join(REPO, "screens", "display-control")


def _key(row, col, label):
    return {
        "position": [row, col],
        "label": label,
        "icon_type": "static",
        "icons": {"default": "icons/blue.png"},
    }


def _write(tmpdir, name, layout, n_keys):
    cols = layout[1]
    cfg = {
        "device": {"layout": layout, "reconnect_timeout_sec": 0, "reconnect_interval_sec": 1},
        "notification": {
            "type": "unix_socket",
            "socket_path": os.path.join(tmpdir, "notify.sock"),
            "state_persist_path": os.path.join(tmpdir, "state.json"),
        },
        "keys": [_key(i // cols, i % cols, f"k{i}") for i in range(n_keys)],
    }
    path = os.path.join(tmpdir, name)
    with open(path, "w") as f:
        json.dump(cfg, f)
    return path


@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp()
    shutil.copytree(FIXTURES, os.path.join(d, "icons"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


class TestConfigForLayout:
    def test_variant_used_when_present(self, tmpdir):
        base = _write(tmpdir, "panel.json", [3, 5], 4)
        mini = _write(tmpdir, "panel-3x2.json", [2, 3], 6)
        assert config_for_layout(base, 2, 3) == mini

    def test_base_used_without_variant(self, tmpdir):
        base = _write(tmpdir, "panel.json", [3, 5], 4)
        assert config_for_layout(base, 2, 3) == base
        assert config_for_layout(base, 3, 5) == base

    def test_name_is_cols_by_rows(self, tmpdir):
        base = _write(tmpdir, "panel.json", [3, 5], 4)
        _write(tmpdir, "panel-2x3.json", [3, 2], 6)   # rows x cols order: must not match
        assert config_for_layout(base, 2, 3) == base


class TestDaemonPicksVariant:
    def _run_briefly(self, daemon):
        """Run the daemon for a moment; return (config path, key count, pages) while live."""
        t = threading.Thread(target=daemon.run)
        t.start()
        time.sleep(0.5)
        seen = (daemon._config_path, len(daemon._config["keys"]), daemon._page_manager.page_count)
        daemon._shutdown_event.set()
        t.join(timeout=5)
        assert not t.is_alive()
        return seen

    def test_mini_deck_loads_3x2_config(self, tmpdir):
        base = _write(tmpdir, "panel.json", [3, 5], 4)
        mini = _write(tmpdir, "panel-3x2.json", [2, 3], 6)
        d = StreamDeckDaemon(config_path=base, simulate=True, simulate_layout=(2, 3))
        assert self._run_briefly(d) == (mini, 6, 1)

    def test_15_key_deck_keeps_base_config(self, tmpdir):
        base = _write(tmpdir, "panel.json", [3, 5], 4)
        _write(tmpdir, "panel-3x2.json", [2, 3], 6)
        d = StreamDeckDaemon(config_path=base, simulate=True)
        assert self._run_briefly(d) == (base, 4, 1)

    def test_swapped_deck_exits_for_restart(self, tmpdir):
        """A different-size deck showing up later makes the daemon exit (systemd restarts it)."""
        base = _write(tmpdir, "panel.json", [3, 5], 4)
        _write(tmpdir, "panel-3x2.json", [2, 3], 6)
        d = StreamDeckDaemon(config_path=base)
        d._config = load_config(base)          # started with the 15-key file
        d._find_deck = lambda: FakeDeck(cols=3, rows=2)
        with pytest.raises(SystemExit) as exc:
            d._run_reconnect_loop()
        assert exc.value.code != 0


class TestShippedDisplayControlConfigs:
    def test_3x2_variant_is_valid_and_fits_one_page(self):
        cfg = load_config(os.path.join(SCREEN, "display-control-3x2.json"))
        assert cfg["device"]["layout"] == [2, 3]
        assert len(cfg["keys"]) == 6          # exactly one page, no navigation arrows

    def test_3x2_keys_match_their_15_key_counterparts(self):
        """Same scripts and notification ids, so both decks drive and show the same state."""
        full = {k["label"]: k for k in load_config(os.path.join(SCREEN, "display-control.json"))["keys"]}
        for k in load_config(os.path.join(SCREEN, "display-control-3x2.json"))["keys"]:
            twin = dict(full[k["label"]], position=k["position"])
            assert k == twin, k["label"]
