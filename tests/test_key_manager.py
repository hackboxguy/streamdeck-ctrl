"""Tests for streamdeck_ctrl.key_manager — state machines and KeyManager."""

import queue
import pytest

from streamdeck_ctrl.key_manager import KeyState, KeyManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_queue():
    return queue.Queue(maxsize=100)


def static_cfg(**overrides):
    cfg = {
        "position": [0, 0],
        "label": "Static",
        "icon_type": "static",
        "icons": {"default": "/icons/default.png"},
    }
    cfg.update(overrides)
    return cfg


def toggle_cfg(**overrides):
    cfg = {
        "position": [0, 0],
        "label": "Toggle",
        "icon_type": "toggle",
        "icons": {"on": "/icons/on.png", "off": "/icons/off.png"},
        "initial_state": "off",
        "notification_id": "test.toggle",
        "action": {"on_press": {"type": "script", "command": "echo {state}"}},
    }
    cfg.update(overrides)
    return cfg


def multistate_cfg(**overrides):
    cfg = {
        "position": [0, 0],
        "label": "Multi",
        "icon_type": "multistate",
        "states": ["a", "b", "c"],
        "icons": {"a": "/icons/a.png", "b": "/icons/b.png", "c": "/icons/c.png"},
        "initial_state": "a",
        "notification_id": "test.multi",
        "action": {"on_press": {"type": "script", "command": "echo {state}"}},
    }
    cfg.update(overrides)
    return cfg


def live_cfg(**overrides):
    cfg = {
        "position": [0, 0],
        "label": "Live",
        "icon_type": "live_value",
        "icons": {"base": "/icons/base.png"},
        "live": {
            "source": "notify_only",
            "format": "{value}°C",
            "text_anchor": "bottom",
            "text_color": "#FFFFFF",
            "font_size": 14,
        },
        "notification_id": "test.live",
    }
    cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------------------
# KeyState — Static
# ---------------------------------------------------------------------------


class TestStaticKey:
    def test_initial_state(self):
        ks = KeyState(static_cfg(), make_queue())
        assert ks.state == "default"

    def test_press_stays_default(self):
        ks = KeyState(static_cfg(), make_queue())
        new_state, action = ks.press()
        assert new_state == "default"

    def test_press_returns_action(self):
        cfg = static_cfg(action={"on_press": {"type": "script", "command": "echo hi"}})
        ks = KeyState(cfg, make_queue())
        _, action = ks.press()
        assert action is not None

    def test_press_no_action(self):
        ks = KeyState(static_cfg(), make_queue())
        _, action = ks.press()
        assert action is None

    def test_press_enqueues_render(self):
        q = make_queue()
        ks = KeyState(static_cfg(), q)
        ks.press()
        assert not q.empty()
        info = q.get_nowait()
        assert info["icon_type"] == "static"
        assert info["icon_path"] == "/icons/default.png"


# ---------------------------------------------------------------------------
# KeyState — Toggle
# ---------------------------------------------------------------------------


class TestToggleKey:
    def test_initial_state_off(self):
        ks = KeyState(toggle_cfg(), make_queue())
        assert ks.state == "off"

    def test_press_off_to_on(self):
        ks = KeyState(toggle_cfg(), make_queue())
        new_state, _ = ks.press()
        assert new_state == "on"

    def test_press_on_to_off(self):
        ks = KeyState(toggle_cfg(initial_state="on"), make_queue())
        new_state, _ = ks.press()
        assert new_state == "off"

    def test_full_cycle(self):
        ks = KeyState(toggle_cfg(), make_queue())
        ks.press()  # off → on
        new_state, _ = ks.press()  # on → off
        assert new_state == "off"

    def test_notify_state_on(self):
        ks = KeyState(toggle_cfg(), make_queue())
        ok, err = ks.notify_state("on")
        assert ok and err is None
        assert ks.state == "on"

    def test_notify_state_off(self):
        ks = KeyState(toggle_cfg(initial_state="on"), make_queue())
        ok, err = ks.notify_state("off")
        assert ok
        assert ks.state == "off"

    def test_notify_invalid_state(self):
        ks = KeyState(toggle_cfg(), make_queue())
        ok, err = ks.notify_state("invalid")
        assert not ok
        assert "invalid state" in err

    def test_render_info_reflects_state(self):
        ks = KeyState(toggle_cfg(), make_queue())
        info = ks.get_render_info()
        assert info["icon_path"] == "/icons/off.png"
        ks.press()
        info = ks.get_render_info()
        assert info["icon_path"] == "/icons/on.png"


# ---------------------------------------------------------------------------
# KeyState — Multistate
# ---------------------------------------------------------------------------


class TestMultistateKey:
    def test_initial_state(self):
        ks = KeyState(multistate_cfg(), make_queue())
        assert ks.state == "a"

    def test_press_cycles(self):
        ks = KeyState(multistate_cfg(), make_queue())
        s1, _ = ks.press()  # a → b
        assert s1 == "b"
        s2, _ = ks.press()  # b → c
        assert s2 == "c"

    def test_press_wraps_around(self):
        ks = KeyState(multistate_cfg(), make_queue())
        ks.press()  # a → b
        ks.press()  # b → c
        s, _ = ks.press()  # c → a
        assert s == "a"

    def test_notify_jump_to_state(self):
        ks = KeyState(multistate_cfg(), make_queue())
        ok, err = ks.notify_state("c")
        assert ok
        assert ks.state == "c"

    def test_notify_invalid_state(self):
        ks = KeyState(multistate_cfg(), make_queue())
        ok, err = ks.notify_state("nonexistent")
        assert not ok
        assert "invalid state" in err

    def test_render_info_icon_matches_state(self):
        ks = KeyState(multistate_cfg(), make_queue())
        assert ks.get_render_info()["icon_path"] == "/icons/a.png"
        ks.press()
        assert ks.get_render_info()["icon_path"] == "/icons/b.png"


# ---------------------------------------------------------------------------
# KeyState — Live Value
# ---------------------------------------------------------------------------


class TestLiveValueKey:
    def test_initial_value_empty(self):
        ks = KeyState(live_cfg(), make_queue())
        assert ks.value == ""

    def test_notify_value(self):
        ks = KeyState(live_cfg(), make_queue())
        ok, err = ks.notify_value("42.5")
        assert ok
        assert ks.value == "42.5"

    def test_notify_value_formats(self):
        ks = KeyState(live_cfg(), make_queue())
        ks.notify_value("42.5")
        info = ks.get_render_info()
        assert info["overlay_text"] == "42.5°C"

    def test_notify_value_float_format_spec(self):
        """Format specs like {value:.1f} should work with numeric values."""
        cfg = live_cfg()
        cfg["live"]["format"] = "{value:.1f}°C"
        ks = KeyState(cfg, make_queue())
        ks.notify_value("42.56")
        info = ks.get_render_info()
        assert info["overlay_text"] == "42.6°C"

    def test_notify_value_string_fallback(self):
        """Non-numeric values should still render with simple format."""
        cfg = live_cfg()
        cfg["live"]["format"] = "{value}"
        ks = KeyState(cfg, make_queue())
        ks.notify_value("N/A")
        info = ks.get_render_info()
        assert info["overlay_text"] == "N/A"

    def test_poll_update(self):
        ks = KeyState(live_cfg(), make_queue())
        ks.update_poll_value("55")
        assert ks.value == "55"

    def test_press_no_state_change(self):
        ks = KeyState(live_cfg(), make_queue())
        ks.notify_value("10")
        state, _ = ks.press()
        assert ks.value == "10"  # value unchanged

    def test_press_with_action(self):
        cfg = live_cfg(action={"on_press": {"type": "script", "command": "echo"}})
        ks = KeyState(cfg, make_queue())
        _, action = ks.press()
        assert action is not None

    def test_notify_state_rejected(self):
        ks = KeyState(live_cfg(), make_queue())
        ok, err = ks.notify_state("on")
        assert not ok
        assert "does not accept state" in err

    def test_render_enqueued_on_value_update(self):
        q = make_queue()
        ks = KeyState(live_cfg(), q)
        # Drain any items from init
        while not q.empty():
            q.get_nowait()
        ks.notify_value("99")
        assert not q.empty()


# ---------------------------------------------------------------------------
# KeyState — Restore
# ---------------------------------------------------------------------------


class TestRestore:
    def test_restore_toggle_state(self):
        ks = KeyState(toggle_cfg(), make_queue())
        ks.restore_state({"state": "on"})
        assert ks.state == "on"

    def test_restore_multistate(self):
        ks = KeyState(multistate_cfg(), make_queue())
        ks.restore_state({"state": "c"})
        assert ks.state == "c"

    def test_restore_live_value(self):
        ks = KeyState(live_cfg(), make_queue())
        ks.restore_state({"value": "77"})
        assert ks.value == "77"

    def test_restore_invalid_state_ignored(self):
        ks = KeyState(toggle_cfg(), make_queue())
        ks.restore_state({"state": "invalid"})
        assert ks.state == "off"  # unchanged


# ---------------------------------------------------------------------------
# KeyManager
# ---------------------------------------------------------------------------


class TestKeyManager:
    def _make_manager(self):
        keys = [
            toggle_cfg(position=[0, 0], label="Toggle1", notification_id="t1"),
            static_cfg(position=[0, 1], label="Static1"),
            multistate_cfg(position=[1, 0], label="Multi1", notification_id="m1"),
            live_cfg(position=[1, 1], label="Live1", notification_id="l1"),
        ]
        q = make_queue()
        return KeyManager(keys, q), q

    def test_get_key_by_position(self):
        km, _ = self._make_manager()
        ks = km.get_key((0, 0))
        assert ks.label == "Toggle1"

    def test_get_key_missing_position(self):
        km, _ = self._make_manager()
        assert km.get_key((2, 2)) is None

    def test_handle_press(self):
        km, _ = self._make_manager()
        result = km.handle_press((0, 0))
        assert result is not None
        ks, new_state, action = result
        assert new_state == "on"

    def test_handle_press_no_key(self):
        km, _ = self._make_manager()
        assert km.handle_press((2, 2)) is None

    def test_handle_notification_state(self):
        km, _ = self._make_manager()
        ok, err = km.handle_notification("t1", state="on")
        assert ok
        assert km.get_key_by_notification_id("t1").state == "on"

    def test_handle_notification_value(self):
        km, _ = self._make_manager()
        ok, err = km.handle_notification("l1", value="42")
        assert ok
        assert km.get_key_by_notification_id("l1").value == "42"

    def test_handle_notification_unknown_id(self):
        km, _ = self._make_manager()
        ok, err = km.handle_notification("unknown.id", state="on")
        assert not ok
        assert "unknown notification_id" in err

    def test_handle_notification_no_state_no_value(self):
        km, _ = self._make_manager()
        ok, err = km.handle_notification("t1")
        assert not ok
        assert "must include" in err

    def test_restore_states(self):
        km, _ = self._make_manager()
        km.restore_states({
            "t1": {"state": "on"},
            "m1": {"state": "c"},
            "l1": {"value": "55"},
        })
        assert km.get_key_by_notification_id("t1").state == "on"
        assert km.get_key_by_notification_id("m1").state == "c"
        assert km.get_key_by_notification_id("l1").value == "55"

    def test_all_keys(self):
        km, _ = self._make_manager()
        assert len(km.all_keys()) == 4

    def test_enqueue_all_renders(self):
        km, q = self._make_manager()
        # Drain queue from init
        while not q.empty():
            q.get_nowait()
        km.enqueue_all_renders()
        assert q.qsize() == 4

    def test_get_persist_data(self):
        km, _ = self._make_manager()
        km.handle_notification("t1", state="on")
        km.handle_notification("m1", state="b")
        km.handle_notification("l1", value="42")
        data = km.get_persist_data()
        assert data["t1"] == {"state": "on"}
        assert data["m1"] == {"state": "b"}
        assert data["l1"] == {"value": "42"}
