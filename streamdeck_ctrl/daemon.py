"""Deck lifecycle, reconnect loop, main event coordinator."""

import logging
import os
import queue
import signal
import threading
import time

from streamdeck_ctrl.action import execute_action, shutdown_executor
from streamdeck_ctrl.config import load_config
from streamdeck_ctrl.icon_renderer import render_key_image, render_live_value_image
from streamdeck_ctrl.key_manager import KeyManager
from streamdeck_ctrl.notifier import Notifier
from streamdeck_ctrl.page_manager import PageManager
from streamdeck_ctrl.state_store import StateStore

logger = logging.getLogger(__name__)


class FakeDeck:
    """Simulated Stream Deck for --simulate mode. Logs image updates."""

    def __init__(self, cols=5, rows=3):
        self._key_count = rows * cols
        self._cols = cols
        self._rows = rows
        self._brightness = 0
        self._open = True
        self._callback = None
        self.image_updates = []  # list of (key_index, image_info)

    def key_count(self):
        return self._key_count

    def key_layout(self):
        return (self._rows, self._cols)

    def key_image_format(self):
        return {"size": (72, 72), "format": "BMP", "rotation": 0, "flip": (True, True)}

    def set_brightness(self, brightness):
        self._brightness = brightness
        logger.info("[SIMULATE] Brightness set to %d", brightness)

    def set_key_image(self, key_index, image_bytes):
        self.image_updates.append((key_index, len(image_bytes) if image_bytes else 0))
        logger.debug("[SIMULATE] Key %d image updated (%d bytes)", key_index, len(image_bytes) if image_bytes else 0)

    def set_key_callback(self, callback):
        self._callback = callback

    def set_key_callback_async(self, callback):
        self._callback = callback

    def reset(self):
        logger.info("[SIMULATE] Deck reset (all keys cleared)")

    def close(self):
        self._open = True
        logger.info("[SIMULATE] Deck closed")

    def is_open(self):
        return self._open

    def simulate_key_press(self, key_index, pressed):
        """Simulate a key press for testing."""
        if self._callback:
            self._callback(self, key_index, pressed)


class StreamDeckDaemon:
    """Main daemon coordinator.

    Manages the deck lifecycle, render thread, poll threads,
    notifier, and state persistence.
    """

    def __init__(self, config_path, socket_path=None, brightness=None,
                 simulate=False):
        self._config_path = config_path
        self._socket_path_override = socket_path
        self._brightness_override = brightness
        self._simulate = simulate

        self._shutdown_event = threading.Event()
        self._render_queue = queue.Queue(maxsize=256)
        self._deck = None
        self._deck_cols = 5  # default, overridden in _setup_deck
        self._key_manager = None
        self._page_manager = None
        self._notifier = None
        self._state_store = None
        self._poll_threads = []
        self._render_thread = None
        self._config = None

    def run(self):
        """Main entry point. Load config, start services, enter reconnect loop."""
        # Load and validate config
        self._config = load_config(self._config_path)

        # Apply overrides
        if self._brightness_override is not None:
            self._config["device"]["brightness"] = self._brightness_override
        socket_path = (
            self._socket_path_override
            or self._config["notification"]["socket_path"]
        )
        self._config["notification"]["socket_path"] = socket_path

        # Initialize key manager
        self._key_manager = KeyManager(self._config["keys"], self._render_queue)

        # Initialize page manager for auto-pagination
        layout = self._config["device"].get("layout", [3, 5])
        config_dir = os.path.dirname(os.path.abspath(self._config_path))
        self._page_manager = PageManager(
            self._config["keys"], layout, config_dir=config_dir
        )

        # Load persisted state
        persist_path = self._config["notification"]["state_persist_path"]
        self._state_store = StateStore(persist_path)
        persisted = self._state_store.load()
        if persisted:
            self._key_manager.restore_states(persisted)

        # Start notifier
        self._notifier = Notifier(socket_path, self._handle_notification)
        self._notifier.start()

        # Start poll threads
        self._start_poll_threads()

        # Install signal handlers (only works from main thread)
        import threading as _threading
        if _threading.current_thread() is _threading.main_thread():
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)

        try:
            if self._simulate:
                self._run_simulate()
            else:
                self._run_reconnect_loop()
        finally:
            self._shutdown()

    def _run_simulate(self):
        """Run in simulate mode with a FakeDeck."""
        logger.info("Running in SIMULATE mode (no hardware)")
        self._deck = FakeDeck()
        self._setup_deck(self._deck)

        # Block until shutdown
        while not self._shutdown_event.is_set():
            self._shutdown_event.wait(timeout=1.0)

    def _run_reconnect_loop(self):
        """USB reconnect loop for real hardware."""
        device_cfg = self._config["device"]
        timeout = device_cfg["reconnect_timeout_sec"]
        interval = device_cfg["reconnect_interval_sec"]

        while not self._shutdown_event.is_set():
            deck = self._find_deck()
            if deck is None:
                start_time = time.monotonic()
                while not self._shutdown_event.is_set():
                    elapsed = time.monotonic() - start_time
                    if timeout > 0 and elapsed >= timeout:
                        logger.error("Reconnect timeout after %ds", timeout)
                        return
                    logger.info("Stream Deck not found, retrying in %ds...", interval)
                    self._shutdown_event.wait(timeout=interval)
                    deck = self._find_deck()
                    if deck:
                        break
                if deck is None:
                    continue

            logger.info("Stream Deck found, opening...")
            try:
                deck.open()
                self._deck = deck
                self._setup_deck(deck)

                # Block until deck disconnects or shutdown
                while not self._shutdown_event.is_set() and deck.is_open():
                    self._shutdown_event.wait(timeout=1.0)

            except Exception:
                logger.exception("Deck error")
            finally:
                try:
                    deck.reset()
                    deck.close()
                except Exception:
                    pass
                self._deck = None
                logger.info("Deck disconnected, entering reconnect loop")

    def _find_deck(self):
        """Find a connected Stream Deck device."""
        try:
            from StreamDeck.DeviceManager import DeviceManager
            devices = DeviceManager().enumerate()
            if devices:
                return devices[0]
        except Exception as e:
            logger.debug("Failed to enumerate devices: %s", e)
        return None

    def _setup_deck(self, deck):
        """Configure deck: brightness, key images, callback, render thread."""
        # Detect column count from deck layout or key count
        if hasattr(deck, 'key_layout'):
            _, self._deck_cols = deck.key_layout()
        else:
            # Real StreamDeck: infer from key count (15→5, 6→3, 32→8)
            key_count = deck.key_count()
            self._deck_cols = {6: 3, 15: 5, 32: 8}.get(key_count, 5)

        deck.set_brightness(self._config["device"]["brightness"])

        # Start render thread
        self._render_thread = threading.Thread(
            target=self._render_loop, args=(deck,), name="render", daemon=True
        )
        self._render_thread.start()

        # Set key callback
        deck.set_key_callback(self._key_callback)

        # Render current page
        self._render_current_page()
        logger.info("Deck setup complete (%d keys, %d pages)",
                     len(self._key_manager.all_keys()), self._page_manager.page_count)

    def _key_callback(self, deck, key_index, pressed):
        """Handle physical key press."""
        if not pressed:
            return  # only handle key-down

        # Map linear key index to (row, col)
        cols = self._deck_cols
        row = key_index // cols
        col = key_index % cols
        physical_pos = (row, col)

        # Check if this is a navigation key (page switch)
        if self._page_manager and self._page_manager.needs_pagination:
            nav_dir = self._page_manager.is_nav_key(physical_pos)
            if nav_dir:
                if self._page_manager.switch_page(nav_dir):
                    self._render_current_page()
                return

        # Map physical position to logical key via page manager
        if self._page_manager and self._page_manager.needs_pagination:
            key_cfg = self._page_manager.get_key_config_at(physical_pos)
            if key_cfg is None:
                return
            position = tuple(key_cfg["position"])
        else:
            position = physical_pos

        result = self._key_manager.handle_press(position)
        if result is None:
            return

        ks, new_state, action = result

        # Persist state
        self._persist_state()

        # Execute action
        if action:
            context = {
                "state": new_state,
                "value": ks.value or "",
                "label": ks.label,
                "key_pos": f"{position[0]},{position[1]}",
            }
            execute_action(action, context)

    def _render_current_page(self):
        """Render all keys for the current page, clearing unused positions."""
        if not self._page_manager:
            self._key_manager.enqueue_all_renders()
            return

        layout = self._page_manager.get_physical_layout()
        rows, cols = self._config["device"].get("layout", [3, 5])

        # Clear all keys first by enqueuing blank renders
        for r in range(rows):
            for c in range(cols):
                pos = (r, c)
                entry = layout.get(pos)
                if entry is None:
                    # Empty slot — enqueue a blank (no icon_path = skipped in render)
                    self._render_queue.put_nowait({
                        "position": pos,
                        "icon_type": "__blank__",
                        "icon_path": None,
                        "label": "",
                    })
                elif entry.get("icon_type") == "__nav__":
                    # Navigation arrow — render directly
                    self._render_queue.put_nowait({
                        "position": pos,
                        "icon_type": "__nav__",
                        "icon_path": entry["icon_path"],
                        "label": entry["label"],
                    })
                else:
                    # User key — get render info from key_manager
                    key_pos = tuple(entry["position"])
                    ks = self._key_manager.get_key(key_pos)
                    if ks:
                        info = ks.get_render_info()
                        # Override position to physical deck position
                        info["position"] = pos
                        self._render_queue.put_nowait(info)

    def _handle_notification(self, notification_id, state=None, value=None):
        """Handle notification from Unix socket (runs in notifier thread)."""
        ok, err = self._key_manager.handle_notification(notification_id, state=state, value=value)
        if ok:
            self._persist_state()
            # If pagination is active, re-render the key only if it's on the current page
            if self._page_manager and self._page_manager.needs_pagination:
                self._render_current_page()
        return ok, err

    def _persist_state(self):
        """Save current key states to disk."""
        if self._state_store:
            data = self._key_manager.get_persist_data()
            self._state_store.save(data)

    def _render_loop(self, deck):
        """Consume render jobs from the queue and update deck key images."""
        key_size = tuple(deck.key_image_format()["size"])

        while not self._shutdown_event.is_set():
            try:
                info = self._render_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            # When pagination is active, skip renders from key_manager's
            # auto-enqueue if the position doesn't match a physical slot
            # on the current page. Page-driven renders use __nav__/__blank__
            # or have their position remapped by _render_current_page().
            if (self._page_manager and self._page_manager.needs_pagination
                    and info.get("icon_type") not in ("__nav__", "__blank__")):
                layout = self._page_manager.get_physical_layout()
                pos = info["position"]
                # Check if this position is a physical slot with a matching key
                entry = layout.get(pos)
                if entry is None or entry.get("icon_type") == "__nav__":
                    continue  # skip — not on current page or is a nav slot

            try:
                self._render_key(deck, info, key_size)
            except Exception:
                logger.exception("Render error for key at %s", info.get("position"))

    def _render_key(self, deck, info, key_size):
        """Render a single key image and push it to the deck."""
        position = info["position"]
        icon_type = info.get("icon_type", "")
        icon_path = info.get("icon_path")

        # Handle blank keys (clear the key image)
        if icon_type == "__blank__" or not icon_path:
            key_index = position[0] * self._deck_cols + position[1]
            from PIL import Image
            blank = Image.new("RGB", key_size, (0, 0, 0))
            if self._simulate:
                deck.set_key_image(key_index, blank.tobytes())
            else:
                from StreamDeck.ImageHelpers import PILHelper
                to_native = getattr(PILHelper, 'to_native_key_format',
                                    getattr(PILHelper, 'to_native_format', None))
                if to_native:
                    deck.set_key_image(key_index, to_native(deck, blank))
            return

        # Map (row, col) to linear key index
        key_index = position[0] * self._deck_cols + position[1]

        if info["icon_type"] == "live_value":
            live = info.get("live_config", {})
            overlay = info.get("overlay_text", "")
            img = render_live_value_image(
                icon_path,
                key_size,
                overlay,
                live.get("text_color", "#FFFFFF"),
                live.get("font_size", 14),
                live.get("font_path"),
                live.get("text_anchor", "bottom"),
            )
        else:
            img = render_key_image(icon_path, key_size=key_size)

        # Convert to deck-native format
        if self._simulate:
            # In simulate mode, just pass the image size
            deck.set_key_image(key_index, img.tobytes())
        else:
            from StreamDeck.ImageHelpers import PILHelper
            # API name varies between library versions
            to_native = getattr(PILHelper, 'to_native_key_format',
                                getattr(PILHelper, 'to_native_format', None))
            if to_native is None:
                raise RuntimeError("PILHelper has no to_native_key_format or to_native_format")
            native = to_native(deck, img)
            deck.set_key_image(key_index, native)

    def _start_poll_threads(self):
        """Start polling threads for live_value keys with poll source."""
        import subprocess

        for ks in self._key_manager.all_keys():
            if ks.icon_type != "live_value":
                continue
            live = ks.config.get("live", {})
            source = live.get("source", "")
            if source not in ("poll", "poll+notify"):
                continue

            poll_cmd = live.get("poll_command")
            interval = live.get("poll_interval_sec", 5)

            if not poll_cmd:
                continue

            t = threading.Thread(
                target=self._poll_loop,
                args=(ks, poll_cmd, interval),
                name=f"poll-{ks.label}",
                daemon=True,
            )
            t.start()
            self._poll_threads.append(t)
            logger.info("Started poll thread for '%s' (every %ds)", ks.label, interval)

    def _poll_loop(self, key_state, command, interval):
        """Poll a command periodically and update key value."""
        import subprocess

        while not self._shutdown_event.is_set():
            try:
                result = subprocess.run(
                    command, shell=True, capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    value = result.stdout.strip().split("\n")[0]
                    key_state.update_poll_value(value)
                    self._persist_state()
                else:
                    logger.warning("Poll command failed for '%s': %s",
                                   key_state.label, result.stderr.strip())
            except subprocess.TimeoutExpired:
                logger.warning("Poll command timed out for '%s'", key_state.label)
            except Exception:
                logger.exception("Poll error for '%s'", key_state.label)

            self._shutdown_event.wait(timeout=interval)

    def _signal_handler(self, signum, frame):
        """Handle SIGTERM/SIGINT for graceful shutdown."""
        sig_name = signal.Signals(signum).name
        logger.info("Received %s, shutting down...", sig_name)
        self._shutdown_event.set()

    def _shutdown(self):
        """Clean shutdown of all components."""
        self._shutdown_event.set()

        # Stop notifier
        if self._notifier:
            self._notifier.stop()

        # Stop action executor
        shutdown_executor()

        # Close deck
        if self._deck and not self._simulate:
            try:
                self._deck.reset()
                self._deck.close()
            except Exception:
                pass

        # Drain render queue
        while not self._render_queue.empty():
            try:
                self._render_queue.get_nowait()
            except queue.Empty:
                break

        logger.info("Daemon shutdown complete")


def dry_run(config_path):
    """Validate config and print key layout without opening the deck."""
    config = load_config(config_path)

    print(f"[DRY RUN] Config loaded: {os.path.abspath(config_path)}")
    print(f"[DRY RUN] Device brightness: {config['device']['brightness']}")
    print(f"[DRY RUN] Notify socket: {config['notification']['socket_path']}")
    layout = config["device"].get("layout", [3, 5])
    print(f"[DRY RUN] Key layout ({len(config['keys'])} keys, {layout[0]} rows x {layout[1]} cols):")

    for key in sorted(config["keys"], key=lambda k: (k["position"][0], k["position"][1])):
        pos = key["position"]
        icon_type = key["icon_type"]
        label = key["label"]
        parts = [f"  [{pos[0]},{pos[1]}] {icon_type:<11} \"{label}\""]

        icons = key.get("icons", {})
        if icon_type == "static":
            parts.append(f"default={icons.get('default', '?')}")
        elif icon_type == "toggle":
            parts.append(f"on={icons.get('on', '?')}  off={icons.get('off', '?')}")
        elif icon_type == "radio":
            parts.append(f"on={icons.get('on', '?')}  off={icons.get('off', '?')}")
        elif icon_type == "multistate":
            parts.append(f"states={','.join(key.get('states', []))}")
        elif icon_type == "live_value":
            parts.append(f"base={icons.get('base', '?')}")
            live = key.get("live", {})
            source = live.get("source", "?")
            if source in ("poll", "poll+notify"):
                parts.append(f"poll={live.get('poll_interval_sec', '?')}s")
            elif source == "notify_only":
                parts.append("notify_only")

        nid = key.get("notification_id")
        if nid:
            parts.append(f"notify={nid}")

        print("  ".join(parts))

    print("[DRY RUN] All icon files resolved and readable. OK.")
    print("[DRY RUN] Exiting (no deck opened).")
