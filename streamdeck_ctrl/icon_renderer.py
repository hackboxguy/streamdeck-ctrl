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
def render_bordered_image(png_path, key_size, border_color, border_width):
    """Render a base icon with a coloured border drawn inside its edges.

    Used by `task` keys to signal progress without needing a separate icon
    file per outcome. A falsy border_color (or zero width) renders the bare
    icon, which is what the "off" half of a blink cycle draws.

    Args:
        png_path: Path to the base icon.
        key_size: (width, height) tuple.
        border_color: Hex colour string, or None for no border.
        border_width: Border thickness in pixels.

    Returns:
        PIL.Image.Image in RGB mode, sized to key_size.
    """
    img = _load_and_scale(png_path, key_size).convert("RGB")
    if not border_color or border_width <= 0:
        return img

    draw = ImageDraw.Draw(img)
    draw.rectangle(
        [0, 0, key_size[0] - 1, key_size[1] - 1],
        outline=border_color,
        width=border_width,
    )
    return img


@lru_cache(maxsize=64)
def render_live_value_image(png_path, key_size, overlay_text,
                            text_color, font_size, font_path, text_anchor):
    """Cached version for live_value keys. All args must be hashable."""
    base = _load_and_scale(png_path, key_size)
    return _render_with_text(base, overlay_text, text_color, font_size,
                             font_path, text_anchor, key_size)


# Characters a wrapped line may end on. An IPv4 breaks after a dot, a MAC or a
# time after a colon -- far more legible than breaking mid-number.
_BREAK_AFTER = ".:-/ "


def _wrap_to_width(text, font, draw, max_width):
    """Split text into lines that fit max_width, breaking after separators.

    A value that fits is returned unchanged, so this costs nothing for the
    short readouts (a temperature, a percentage) live_value usually carries.
    """
    def width(s):
        return draw.textbbox((0, 0), s, font=font)[2]

    if width(text) <= max_width:
        return [text]

    # Chunks that each end on a break character (the last may not).
    atoms, current = [], ""
    for ch in text:
        current += ch
        if ch in _BREAK_AFTER:
            atoms.append(current)
            current = ""
    if current:
        atoms.append(current)

    lines, line = [], ""
    for atom in atoms:
        if line and width((line + atom).strip()) > max_width:
            lines.append(line.strip())
            line = atom
        else:
            line += atom
    if line.strip():
        lines.append(line.strip())

    # A single atom wider than the key (a long word) still has to fit: hard-break it.
    out = []
    for line in lines:
        while width(line) > max_width and len(line) > 1:
            cut = len(line) - 1
            while cut > 1 and width(line[:cut]) > max_width:
                cut -= 1
            out.append(line[:cut])
            line = line[cut:]
        if line:
            out.append(line)
    return out


def _render_with_text(base, text, text_color, font_size, font_path,
                      text_anchor, key_size):
    """Composite text overlay onto a base image, wrapping if it would not fit."""
    img = base.copy()
    draw = ImageDraw.Draw(img)
    font = _load_font(font_path, font_size)

    margin = 4
    lines = _wrap_to_width(str(text), font, draw, key_size[0] - 2 * margin)

    # Uniform line height, so multi-line values do not jitter as digits change.
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    block_h = line_h * len(lines)

    if text_anchor == "top":
        y = margin
    elif text_anchor == "center":
        y = (key_size[1] - block_h) // 2
    else:  # bottom
        y = key_size[1] - block_h - margin

    shadow_color = "#000000"
    for line in lines:
        line_w = draw.textbbox((0, 0), line, font=font)[2]
        x = (key_size[0] - line_w) // 2
        # Shadow first, so neighbouring lines cannot darken each other's glyphs.
        for dx, dy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
            draw.text((x + dx, y + dy), line, font=font, fill=shadow_color)
        draw.text((x, y), line, font=font, fill=text_color)
        y += line_h

    return img.convert("RGB")


def clear_cache():
    """Clear all image caches. Call on config reload."""
    _load_and_scale.cache_clear()
    render_bordered_image.cache_clear()
    render_live_value_image.cache_clear()
