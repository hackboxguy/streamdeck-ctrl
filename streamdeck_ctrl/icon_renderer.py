"""PIL-based image renderer for Stream Deck keys, with LRU cache."""

import logging
import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# Default font — search relative to package, then system paths
_FONT_SEARCH_PATHS = [
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "fonts", "DejaVuSans-Bold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
_DEFAULT_FONT_PATH = next(
    (p for p in _FONT_SEARCH_PATHS if os.path.isfile(p)),
    _FONT_SEARCH_PATHS[0],  # fallback to first path even if missing
)

# Default key size (Stream Deck MK.2); overridden at runtime by deck.key_image_format()
DEFAULT_KEY_SIZE = (72, 72)


def _load_font(font_path, font_size):
    """Load a TrueType font, falling back to bundled then PIL default."""
    for path in (font_path, _DEFAULT_FONT_PATH):
        if path:
            try:
                return ImageFont.truetype(path, font_size)
            except (OSError, IOError):
                logger.debug("Font not found: %s, trying fallback", path)
    logger.warning("No TrueType font available, using PIL default bitmap font")
    return ImageFont.load_default()


@lru_cache(maxsize=64)
def _load_and_scale(png_path, size):
    """Load a PNG and scale it to the target size. Cached."""
    img = Image.open(png_path).convert("RGBA")
    if img.size != size:
        img = img.resize(size, Image.LANCZOS)
    return img


def render_key_image(png_path, key_size=None, overlay_text=None,
                     text_color="#FFFFFF", font_size=14, font_path=None,
                     text_anchor="bottom"):
    """Render a key image with optional text overlay.

    Args:
        png_path: Path to the base PNG icon.
        key_size: (width, height) tuple. Defaults to DEFAULT_KEY_SIZE.
        overlay_text: Optional text to draw on the image.
        text_color: Hex color string for the text (e.g. "#FFFFFF").
        font_size: Font size in points.
        font_path: Optional path to a TTF font file.
        text_anchor: Vertical position: "top", "center", or "bottom".

    Returns:
        PIL.Image.Image in RGB mode, sized to key_size.
    """
    if key_size is None:
        key_size = DEFAULT_KEY_SIZE

    # Load and scale base image (cached)
    base = _load_and_scale(png_path, key_size)

    if overlay_text is None:
        return base.convert("RGB")

    # Composite with text overlay — not cached at base level,
    # but the base PNG load is cached
    return _render_with_text(base, overlay_text, text_color, font_size,
                             font_path, text_anchor, key_size)


@lru_cache(maxsize=64)
def render_live_value_image(png_path, key_size, overlay_text,
                            text_color, font_size, font_path, text_anchor):
    """Cached version for live_value keys. All args must be hashable."""
    base = _load_and_scale(png_path, key_size)
    return _render_with_text(base, overlay_text, text_color, font_size,
                             font_path, text_anchor, key_size)


def _render_with_text(base, text, text_color, font_size, font_path,
                      text_anchor, key_size):
    """Composite text overlay onto a base image."""
    img = base.copy()
    draw = ImageDraw.Draw(img)
    font = _load_font(font_path, font_size)

    # Calculate text bounding box
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # Horizontal: always centered
    x = (key_size[0] - text_w) // 2

    # Vertical: based on anchor
    margin = 4
    if text_anchor == "top":
        y = margin
    elif text_anchor == "center":
        y = (key_size[1] - text_h) // 2
    else:  # bottom
        y = key_size[1] - text_h - margin

    # Draw text shadow for readability
    shadow_color = "#000000"
    for dx, dy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
        draw.text((x + dx, y + dy), text, font=font, fill=shadow_color)
    draw.text((x, y), text, font=font, fill=text_color)

    return img.convert("RGB")


def clear_cache():
    """Clear all image caches. Call on config reload."""
    _load_and_scale.cache_clear()
    render_live_value_image.cache_clear()
