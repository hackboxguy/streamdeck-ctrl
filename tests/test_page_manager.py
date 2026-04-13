"""Tests for streamdeck_ctrl.page_manager — multi-page pagination."""

import pytest

from streamdeck_ctrl.page_manager import PageManager


def _make_keys(n):
    """Create n dummy key configs."""
    return [
        {"position": [i // 5, i % 5], "label": f"Key{i}", "icon_type": "static",
         "icons": {"default": f"icon{i}.bmp"}}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# No pagination (≤15 keys)
# ---------------------------------------------------------------------------


class TestNoPagination:
    def test_15_keys_no_pagination(self):
        pm = PageManager(_make_keys(15), [3, 5])
        assert pm.page_count == 1
        assert not pm.needs_pagination

    def test_10_keys_no_pagination(self):
        pm = PageManager(_make_keys(10), [3, 5])
        assert pm.page_count == 1
        assert not pm.needs_pagination

    def test_1_key_no_pagination(self):
        pm = PageManager(_make_keys(1), [3, 5])
        assert pm.page_count == 1

    def test_layout_has_all_keys(self):
        keys = _make_keys(5)
        pm = PageManager(keys, [3, 5])
        layout = pm.get_physical_layout()
        assert len(layout) == 5
        # No nav keys
        assert all(v.get("icon_type") != "__nav__" for v in layout.values())


# ---------------------------------------------------------------------------
# Pagination (>15 keys)
# ---------------------------------------------------------------------------


class TestPagination:
    def test_16_keys_two_pages(self):
        pm = PageManager(_make_keys(16), [3, 5])
        assert pm.page_count == 2
        assert pm.needs_pagination

    def test_page1_has_14_keys_plus_right_arrow(self):
        pm = PageManager(_make_keys(16), [3, 5])
        layout = pm.get_physical_layout(0)
        user_keys = [v for v in layout.values() if v.get("icon_type") != "__nav__"]
        nav_keys = [v for v in layout.values() if v.get("icon_type") == "__nav__"]
        assert len(user_keys) == 14
        assert len(nav_keys) == 1
        assert nav_keys[0]["direction"] == "right"

    def test_page2_has_left_arrow_plus_remaining(self):
        pm = PageManager(_make_keys(16), [3, 5])
        layout = pm.get_physical_layout(1)
        user_keys = [v for v in layout.values() if v.get("icon_type") != "__nav__"]
        nav_keys = [v for v in layout.values() if v.get("icon_type") == "__nav__"]
        assert len(user_keys) == 2
        assert len(nav_keys) == 1
        assert nav_keys[0]["direction"] == "left"

    def test_right_arrow_at_bottom_right(self):
        pm = PageManager(_make_keys(16), [3, 5])
        layout = pm.get_physical_layout(0)
        assert layout[(2, 4)]["icon_type"] == "__nav__"
        assert layout[(2, 4)]["direction"] == "right"

    def test_left_arrow_at_bottom_left(self):
        pm = PageManager(_make_keys(16), [3, 5])
        layout = pm.get_physical_layout(1)
        assert layout[(2, 0)]["icon_type"] == "__nav__"
        assert layout[(2, 0)]["direction"] == "left"

    def test_28_keys_two_pages(self):
        """Page 1: 14 keys + right. Page 2: left + 14 keys."""
        pm = PageManager(_make_keys(28), [3, 5])
        assert pm.page_count == 2

    def test_29_keys_three_pages(self):
        """Page 1: 14 + right. Page 2: left + 13 + right. Page 3: left + 2."""
        pm = PageManager(_make_keys(29), [3, 5])
        assert pm.page_count == 3

    def test_middle_page_has_both_arrows(self):
        pm = PageManager(_make_keys(29), [3, 5])
        layout = pm.get_physical_layout(1)
        nav_keys = {v["direction"] for v in layout.values() if v.get("icon_type") == "__nav__"}
        assert nav_keys == {"left", "right"}

    def test_middle_page_has_13_user_keys(self):
        """Middle page: 15 slots - left arrow - right arrow = 13 user keys."""
        pm = PageManager(_make_keys(29), [3, 5])
        layout = pm.get_physical_layout(1)
        user_keys = [v for v in layout.values() if v.get("icon_type") != "__nav__"]
        assert len(user_keys) == 13

    def test_all_keys_accounted_for(self):
        """Total user keys across all pages should match input count."""
        for n in [16, 17, 27, 28, 40]:
            pm = PageManager(_make_keys(n), [3, 5])
            total = 0
            for p in range(pm.page_count):
                layout = pm.get_physical_layout(p)
                total += sum(1 for v in layout.values() if v.get("icon_type") != "__nav__")
            assert total == n, f"Failed for n={n}: got {total}"


# ---------------------------------------------------------------------------
# Page switching
# ---------------------------------------------------------------------------


class TestPageSwitching:
    def test_starts_at_page_0(self):
        pm = PageManager(_make_keys(16), [3, 5])
        assert pm.current_page == 0

    def test_switch_right(self):
        pm = PageManager(_make_keys(16), [3, 5])
        assert pm.switch_page("right") is True
        assert pm.current_page == 1

    def test_switch_left(self):
        pm = PageManager(_make_keys(16), [3, 5])
        pm.switch_page("right")
        assert pm.switch_page("left") is True
        assert pm.current_page == 0

    def test_cannot_switch_past_last(self):
        pm = PageManager(_make_keys(16), [3, 5])
        pm.switch_page("right")
        assert pm.switch_page("right") is False
        assert pm.current_page == 1

    def test_cannot_switch_before_first(self):
        pm = PageManager(_make_keys(16), [3, 5])
        assert pm.switch_page("left") is False
        assert pm.current_page == 0


# ---------------------------------------------------------------------------
# Navigation key detection
# ---------------------------------------------------------------------------


class TestNavKeyDetection:
    def test_is_nav_key_right(self):
        pm = PageManager(_make_keys(16), [3, 5])
        assert pm.is_nav_key((2, 4)) == "right"

    def test_is_nav_key_left(self):
        pm = PageManager(_make_keys(16), [3, 5])
        pm.switch_page("right")
        assert pm.is_nav_key((2, 0)) == "left"

    def test_user_key_is_not_nav(self):
        pm = PageManager(_make_keys(16), [3, 5])
        assert pm.is_nav_key((0, 0)) is None

    def test_empty_slot_is_not_nav(self):
        pm = PageManager(_make_keys(16), [3, 5])
        pm.switch_page("right")
        assert pm.is_nav_key((1, 0)) is None

    def test_get_key_config_at(self):
        keys = _make_keys(16)
        pm = PageManager(keys, [3, 5])
        cfg = pm.get_key_config_at((0, 0))
        assert cfg is not None
        assert cfg["label"] == "Key0"

    def test_get_key_config_at_nav_returns_none(self):
        pm = PageManager(_make_keys(16), [3, 5])
        assert pm.get_key_config_at((2, 4)) is None  # right arrow slot


# ---------------------------------------------------------------------------
# Custom layout (non 3x5)
# ---------------------------------------------------------------------------


class TestCustomLayout:
    def test_2x3_no_pagination(self):
        keys = _make_keys(6)
        pm = PageManager(keys, [2, 3])
        assert pm.page_count == 1

    def test_2x3_with_pagination(self):
        keys = _make_keys(8)
        pm = PageManager(keys, [2, 3])
        assert pm.page_count == 2
        assert pm.needs_pagination
