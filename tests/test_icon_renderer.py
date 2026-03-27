"""Tests for streamdeck_ctrl.icon_renderer — PIL rendering and LRU cache."""

import os
import pytest
from PIL import Image

from streamdeck_ctrl.icon_renderer import (
    render_key_image,
    render_live_value_image,
    clear_cache,
    _load_and_scale,
    _DEFAULT_FONT_PATH,
)

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "icons")
RED = os.path.join(FIXTURES, "red.png")
GREEN = os.path.join(FIXTURES, "green.png")
GRAY = os.path.join(FIXTURES, "gray.png")


@pytest.fixture(autouse=True)
def _clear_caches():
    """Clear caches before each test for isolation."""
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# Basic rendering
# ---------------------------------------------------------------------------


class TestBasicRendering:
    def test_static_icon_returns_correct_size(self):
        img = render_key_image(RED)
        assert img.size == (72, 72)
        assert img.mode == "RGB"

    def test_static_icon_custom_size(self):
        img = render_key_image(RED, key_size=(96, 96))
        assert img.size == (96, 96)

    def test_static_icon_pixel_color(self):
        """Red icon should have red pixels."""
        img = render_key_image(RED)
        r, g, b = img.getpixel((36, 36))
        assert r == 255 and g == 0 and b == 0

    def test_toggle_on_off_different_images(self):
        img_on = render_key_image(GREEN)
        img_off = render_key_image(RED)
        assert img_on.getpixel((36, 36)) != img_off.getpixel((36, 36))

    def test_missing_icon_raises(self):
        with pytest.raises(FileNotFoundError):
            render_key_image("/nonexistent/icon.png")


# ---------------------------------------------------------------------------
# Text overlay
# ---------------------------------------------------------------------------


class TestTextOverlay:
    def test_overlay_text_renders(self):
        img_plain = render_key_image(GRAY)
        img_text = render_key_image(GRAY, overlay_text="42°C")
        # Images should differ since text was drawn
        assert img_plain.tobytes() != img_text.tobytes()

    def test_overlay_text_bottom_anchor(self):
        img = render_key_image(GRAY, overlay_text="Test", text_anchor="bottom")
        assert img.size == (72, 72)

    def test_overlay_text_top_anchor(self):
        img = render_key_image(GRAY, overlay_text="Test", text_anchor="top")
        assert img.size == (72, 72)

    def test_overlay_text_center_anchor(self):
        img = render_key_image(GRAY, overlay_text="Test", text_anchor="center")
        assert img.size == (72, 72)

    def test_overlay_text_custom_color(self):
        img = render_key_image(GRAY, overlay_text="X", text_color="#FF0000")
        assert img.size == (72, 72)

    def test_overlay_text_custom_font_size(self):
        img_small = render_key_image(GRAY, overlay_text="ABC", font_size=10)
        img_large = render_key_image(GRAY, overlay_text="ABC", font_size=24)
        # Different font sizes should produce different images
        assert img_small.tobytes() != img_large.tobytes()

    def test_overlay_with_bundled_font(self):
        """Bundled DejaVuSans-Bold.ttf should be found and used."""
        assert os.path.isfile(_DEFAULT_FONT_PATH)
        img = render_key_image(GRAY, overlay_text="OK", font_path=None)
        assert img.size == (72, 72)

    def test_overlay_with_missing_font_falls_back(self):
        """Missing custom font should fall back to bundled font."""
        img = render_key_image(
            GRAY, overlay_text="FB", font_path="/nonexistent/font.ttf"
        )
        assert img.size == (72, 72)


# ---------------------------------------------------------------------------
# LRU cache
# ---------------------------------------------------------------------------


class TestCache:
    def test_base_image_cached(self):
        """Same PNG+size should return cached object."""
        _load_and_scale(RED, (72, 72))
        _load_and_scale(RED, (72, 72))
        info = _load_and_scale.cache_info()
        assert info.hits >= 1

    def test_different_size_not_cached(self):
        _load_and_scale(RED, (72, 72))
        _load_and_scale(RED, (96, 96))
        info = _load_and_scale.cache_info()
        assert info.misses >= 2

    def test_live_value_cached_by_text(self):
        """Same args should hit cache."""
        args = (GRAY, (72, 72), "42", "#FFFFFF", 14, None, "bottom")
        render_live_value_image(*args)
        render_live_value_image(*args)
        info = render_live_value_image.cache_info()
        assert info.hits >= 1

    def test_live_value_different_text_misses(self):
        """Different text should miss cache."""
        args1 = (GRAY, (72, 72), "42", "#FFFFFF", 14, None, "bottom")
        args2 = (GRAY, (72, 72), "99", "#FFFFFF", 14, None, "bottom")
        render_live_value_image(*args1)
        render_live_value_image(*args2)
        info = render_live_value_image.cache_info()
        assert info.misses >= 2

    def test_clear_cache_resets(self):
        _load_and_scale(RED, (72, 72))
        clear_cache()
        info = _load_and_scale.cache_info()
        assert info.hits == 0 and info.misses == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_overlay_text(self):
        """Empty string overlay should still render."""
        img = render_key_image(GRAY, overlay_text="")
        assert img.size == (72, 72)

    def test_long_overlay_text(self):
        """Long text should not crash (may overflow, but shouldn't error)."""
        img = render_key_image(GRAY, overlay_text="A very long text string here")
        assert img.size == (72, 72)

    def test_special_chars_in_text(self):
        img = render_key_image(GRAY, overlay_text="°C % ★")
        assert img.size == (72, 72)
