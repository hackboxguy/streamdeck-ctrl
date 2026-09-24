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


class PluggableDeck(FakeDeck):
    """A FakeDeck that can be opened and unplugged, for the reconnect loop."""

    def __init__(self, cols, rows):
        super().__init__(cols=cols, rows=rows)
        self.plugged = True

    def open(self):
        pass

    def is_open(self):
        return self.plugged


class TestLiveRepagination:
    """Without a variant file, a deck of another size gets the same keys re-paginated."""

    def _daemon(self, tmpdir, n_keys=12):
        base = _write(tmpdir, "panel.json", [3, 5], n_keys)
        d = StreamDeckDaemon(config_path=base)
        slot = {"deck": None}
        d._find_deck = lambda: slot["deck"] if slot["deck"] and slot["deck"].plugged else None
        return d, slot

    def _start(self, d):
        t = threading.Thread(target=d.run)
        t.start()
        return t

    def _stop(self, d, t):
        d._shutdown_event.set()
        t.join(timeout=5)
        assert not t.is_alive()

    def test_mini_without_variant_is_paginated_at_start(self, tmpdir):
        d, slot = self._daemon(tmpdir)
        slot["deck"] = PluggableDeck(cols=3, rows=2)
        t = self._start(d)
        time.sleep(0.5)
        try:
            # 12 keys on 6 slots: 5 + arrow, <- + 4 + ->, <- + 3
            assert d._layout == (2, 3)
            assert d._page_manager.page_count == 3
        finally:
            self._stop(d, t)

    def test_swap_15_key_for_mini_and_back_without_restart(self, tmpdir):
        d, slot = self._daemon(tmpdir)
        slot["deck"] = PluggableDeck(cols=5, rows=3)
        t = self._start(d)
        try:
            time.sleep(0.5)
            assert (d._layout, d._page_manager.page_count) == ((3, 5), 1)
            keys_before = d._key_manager

            slot["deck"].plugged = False              # unplug the 15-key deck
            time.sleep(0.3)
            slot["deck"] = PluggableDeck(cols=3, rows=2)   # plug in a Mini
            time.sleep(d._config["device"]["reconnect_interval_sec"] + 1.0)
            assert t.is_alive()                        # re-paginated in place, no exit
            assert (d._layout, d._page_manager.page_count) == ((2, 3), 3)
            assert d._key_manager is keys_before       # same keys and states
            assert d._deck is slot["deck"]

            slot["deck"].plugged = False              # and back to 15 keys
            time.sleep(0.3)
            slot["deck"] = PluggableDeck(cols=5, rows=3)
            time.sleep(d._config["device"]["reconnect_interval_sec"] + 1.0)
            assert (d._layout, d._page_manager.page_count) == ((3, 5), 1)
        finally:
            self._stop(d, t)

    def test_nav_arrows_on_mini_pages(self, tmpdir):
        d, slot = self._daemon(tmpdir)
        slot["deck"] = PluggableDeck(cols=3, rows=2)
        t = self._start(d)
        time.sleep(0.5)
        try:
            pm = d._page_manager
            first = pm.get_physical_layout(0)
            middle = pm.get_physical_layout(1)
            assert first[(1, 2)]["icon_type"] == "__nav__"                 # -> bottom-right
            assert middle[(1, 0)]["icon_type"] == "__nav__"                # <- bottom-left
            assert middle[(1, 2)]["icon_type"] == "__nav__"
        finally:
            self._stop(d, t)
