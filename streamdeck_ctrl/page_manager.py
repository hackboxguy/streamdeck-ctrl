"""Multi-page support for Stream Deck key layouts.

Auto-paginates when more keys are configured than fit on a single page.
Navigation arrows are rendered automatically at fixed positions:
  - Right arrow: [max_row, max_col] (bottom-right) on non-last pages
  - Left arrow:  [max_row, 0] (bottom-left) on non-first pages
"""

import logging
import os

logger = logging.getLogger(__name__)

# Arrow icon paths (relative to the screen directory)
_ARROW_RIGHT = "right-arrow.bmp"
_ARROW_LEFT = "left-arrow.bmp"


class PageManager:
    """Manages multi-page key layout with automatic pagination.

    Takes a flat list of key configs and splits them into pages.
    Provides mapping between physical deck positions and logical keys.
    """

    def __init__(self, keys_config, layout, config_dir=""):
        """
        Args:
            keys_config: List of key config dicts (from JSON).
            layout: [rows, cols] — deck grid size.
            config_dir: Directory containing the config file (for icon resolution).
        """
        self._rows, self._cols = layout
        self._total_slots = self._rows * self._cols
        self._config_dir = config_dir
        self._current_page = 0

        # Positions reserved for navigation arrows
        self._right_arrow_pos = (self._rows - 1, self._cols - 1)  # bottom-right
        self._left_arrow_pos = (self._rows - 1, 0)  # bottom-left

        # Resolve arrow icon paths
        self._right_arrow_icon = self._resolve_icon(_ARROW_RIGHT)
        self._left_arrow_icon = self._resolve_icon(_ARROW_LEFT)

        # Build pages
        self._pages = self._paginate(keys_config)

        if len(self._pages) > 1:
            logger.info("Pagination: %d keys → %d pages", len(keys_config), len(self._pages))

    def _resolve_icon(self, filename):
        """Resolve arrow icon path relative to config directory."""
        if self._config_dir:
            path = os.path.join(self._config_dir, filename)
            if os.path.isfile(path):
                return path
        return filename

    def _paginate(self, keys_config):
        """Split keys into pages.

        Page 1: up to (total_slots - 1) keys + right arrow at bottom-right
        Middle pages: left arrow at bottom-left + keys + right arrow at bottom-right
        Last page: left arrow at bottom-left + remaining keys
        """
        total_keys = len(keys_config)

        if total_keys <= self._total_slots:
            # Everything fits on one page, no pagination needed
            return [keys_config[:]]

        pages = []
        key_index = 0

        # Page 1: total_slots - 1 user keys (reserve 1 for right arrow)
        first_page_slots = self._total_slots - 1
        pages.append(keys_config[key_index:key_index + first_page_slots])
        key_index += first_page_slots

        # Middle and last pages
        while key_index < total_keys:
            remaining = total_keys - key_index
            # Determine slots available on this page
            is_last_page = remaining <= (self._total_slots - 1)  # -1 for left arrow

            if is_last_page:
                # Last page: left arrow + remaining keys
                pages.append(keys_config[key_index:key_index + remaining])
                key_index += remaining
            else:
                # Middle page: left arrow + keys + right arrow = total_slots - 2 user keys
                middle_page_slots = self._total_slots - 2
                pages.append(keys_config[key_index:key_index + middle_page_slots])
                key_index += middle_page_slots

        return pages

    @property
    def page_count(self):
        return len(self._pages)

    @property
    def current_page(self):
        return self._current_page

    @property
    def needs_pagination(self):
        return len(self._pages) > 1

    def get_physical_layout(self, page=None):
        """Get the physical key layout for a page.

        Returns:
            dict mapping (row, col) → key_config or nav marker.
            Nav markers are dicts with icon_type="__nav__" and direction="left"/"right".
        """
        if page is None:
            page = self._current_page

        if page < 0 or page >= len(self._pages):
            return {}

        page_keys = self._pages[page]
        layout = {}
        is_first = (page == 0)
        is_last = (page == len(self._pages) - 1)

        # Determine which physical slots are available for user keys
        all_positions = [
            (r, c) for r in range(self._rows) for c in range(self._cols)
        ]

        # Remove nav arrow positions from available slots
        if not is_first:
            all_positions.remove(self._left_arrow_pos)
        if not is_last:
            all_positions.remove(self._right_arrow_pos)

        # Assign user keys to available positions (in order)
        for i, key_cfg in enumerate(page_keys):
            if i >= len(all_positions):
                break
            pos = all_positions[i]
            layout[pos] = key_cfg

        # Add navigation arrows
        if not is_last:
            layout[self._right_arrow_pos] = {
                "icon_type": "__nav__",
                "direction": "right",
                "icon_path": self._right_arrow_icon,
                "label": "Next Page",
            }
        if not is_first:
            layout[self._left_arrow_pos] = {
                "icon_type": "__nav__",
                "direction": "left",
                "icon_path": self._left_arrow_icon,
                "label": "Previous Page",
            }

        return layout

    def switch_page(self, direction):
        """Switch to next/previous page.

        Args:
            direction: "right" for next page, "left" for previous.

        Returns:
            True if page changed, False if already at boundary.
        """
        if direction == "right" and self._current_page < len(self._pages) - 1:
            self._current_page += 1
            logger.info("Page switch → page %d/%d", self._current_page + 1, len(self._pages))
            return True
        elif direction == "left" and self._current_page > 0:
            self._current_page -= 1
            logger.info("Page switch → page %d/%d", self._current_page + 1, len(self._pages))
            return True
        return False

    def is_nav_key(self, physical_pos):
        """Check if a physical position is a navigation key on the current page.

        Returns:
            "left", "right", or None.
        """
        layout = self.get_physical_layout()
        entry = layout.get(physical_pos)
        if entry and isinstance(entry, dict) and entry.get("icon_type") == "__nav__":
            return entry["direction"]
        return None

    def get_key_config_at(self, physical_pos):
        """Get the user key config at a physical position on the current page.

        Returns:
            key_config dict or None (if position is empty or a nav key).
        """
        layout = self.get_physical_layout()
        entry = layout.get(physical_pos)
        if entry and isinstance(entry, dict) and entry.get("icon_type") != "__nav__":
            return entry
        return None
