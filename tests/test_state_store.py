"""Tests for streamdeck_ctrl.state_store — atomic persistence."""

import json
import os
import tempfile
import shutil
import threading
import pytest

from streamdeck_ctrl.state_store import StateStore


@pytest.fixture
def tmpdir():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


@pytest.fixture
def store(tmpdir):
    return StateStore(os.path.join(tmpdir, "state.json"))


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_missing_file_returns_empty(self, store):
        assert store.load() == {}

    def test_load_valid_file(self, store):
        data = {"backlight.state": {"state": "on"}}
        with open(store.path, "w") as f:
            json.dump(data, f)
        assert store.load() == data

    def test_load_corrupt_file_returns_empty(self, store):
        with open(store.path, "w") as f:
            f.write("{corrupt json")
        assert store.load() == {}

    def test_load_empty_file_returns_empty(self, store):
        with open(store.path, "w") as f:
            f.write("")
        assert store.load() == {}


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


class TestSave:
    def test_save_creates_file(self, store):
        data = {"test.key": {"state": "on"}}
        store.save(data)
        assert os.path.isfile(store.path)

    def test_save_round_trip(self, store):
        data = {
            "backlight.state": {"state": "on"},
            "display.mode": {"state": "hdr"},
            "sensor.temp": {"value": "42.5"},
        }
        store.save(data)
        loaded = store.load()
        assert loaded == data

    def test_save_overwrites_previous(self, store):
        store.save({"key": {"state": "a"}})
        store.save({"key": {"state": "b"}})
        assert store.load() == {"key": {"state": "b"}}

    def test_save_no_tmp_file_remains(self, store):
        store.save({"key": {"state": "on"}})
        tmp_path = store.path + ".tmp"
        assert not os.path.exists(tmp_path)

    def test_save_creates_parent_dirs(self, tmpdir):
        path = os.path.join(tmpdir, "sub", "dir", "state.json")
        store = StateStore(path)
        store.save({"key": {"state": "on"}})
        assert os.path.isfile(path)


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_saves(self, store):
        """Multiple threads saving should not corrupt the file."""
        errors = []

        def save_data(i):
            try:
                store.save({f"key{i}": {"state": f"val{i}"}})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=save_data, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # File should be valid JSON (one of the writes won)
        loaded = store.load()
        assert isinstance(loaded, dict)
        assert len(loaded) == 1  # last writer wins

    def test_concurrent_save_and_load(self, store):
        """Save and load from different threads shouldn't crash."""
        store.save({"initial": {"state": "on"}})
        errors = []

        def do_save():
            for _ in range(50):
                try:
                    store.save({"key": {"state": "on"}})
                except Exception as e:
                    errors.append(e)

        def do_load():
            for _ in range(50):
                try:
                    store.load()
                except Exception as e:
                    errors.append(e)

        t1 = threading.Thread(target=do_save)
        t2 = threading.Thread(target=do_load)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not errors


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_data(self, store):
        store.save({})
        assert store.load() == {}

    def test_unicode_values(self, store):
        data = {"sensor": {"value": "42.5°C"}}
        store.save(data)
        assert store.load() == data

    def test_nested_data(self, store):
        data = {"key": {"state": "on", "extra": {"nested": True}}}
        store.save(data)
        assert store.load() == data
