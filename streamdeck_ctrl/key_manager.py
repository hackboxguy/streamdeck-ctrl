"""Per-key state machines for all 4 icon types, render job enqueueing."""

import logging
import queue

logger = logging.getLogger(__name__)


class KeyState:
    """State machine for a single Stream Deck key.

    Handles press → next-state transitions and notify → jump-to-state.
    Enqueues render jobs to the shared render_queue.
    """

    def __init__(self, key_config, render_queue):
        self.config = key_config
        self.render_queue = render_queue
        self.icon_type = key_config["icon_type"]
        self.label = key_config["label"]
        self.position = tuple(key_config["position"])
        self.notification_id = key_config.get("notification_id")

        # State initialization
        if self.icon_type == "static":
            self._state = "default"
        elif self.icon_type == "toggle":
            self._state = key_config.get("initial_state", "off")
        elif self.icon_type == "multistate":
            self._states = key_config["states"]
            self._state = key_config.get("initial_state", self._states[0])
        elif self.icon_type == "live_value":
            self._state = "default"
            self._value = ""
            self._live_config = key_config.get("live", {})

    @property
    def state(self):
        return self._state

    @property
    def value(self):
        if self.icon_type == "live_value":
            return self._value
        return None

    def press(self):
        """Handle a key press. Returns the new state and action config (or None).

        For toggle/multistate, advances to the next state.
        For static, stays in 'default'.
        For live_value, state doesn't change.

        Returns:
            tuple: (new_state, action_config_or_none)
        """
        action = self.config.get("action")

        if self.icon_type == "static":
            self._enqueue_render()
            return self._state, action

        elif self.icon_type == "toggle":
            self._state = "on" if self._state == "off" else "off"
            self._enqueue_render()
            return self._state, action

        elif self.icon_type == "multistate":
            idx = self._states.index(self._state)
            self._state = self._states[(idx + 1) % len(self._states)]
            self._enqueue_render()
            return self._state, action

        elif self.icon_type == "live_value":
            # No state change on press, but action may fire
            self._enqueue_render()
            return self._state, action

        return self._state, None

    def notify_state(self, new_state):
        """Handle an external state notification (toggle/multistate).

        Args:
            new_state: The state to jump to.

        Returns:
            tuple: (success: bool, error_message: str or None)
        """
        if self.icon_type == "toggle":
            if new_state not in ("on", "off"):
                return False, (
                    f"invalid state '{new_state}' for toggle key "
                    f"'{self.label}', valid: on, off"
                )
            self._state = new_state
            self._enqueue_render()
            return True, None

        elif self.icon_type == "multistate":
            if new_state not in self._states:
                return False, (
                    f"invalid state '{new_state}' for key '{self.label}', "
                    f"valid: {','.join(self._states)}"
                )
            self._state = new_state
            self._enqueue_render()
            return True, None

        return False, (
            f"key '{self.label}' (type={self.icon_type}) "
            f"does not accept state notifications"
        )

    def notify_value(self, new_value):
        """Handle an external value notification (live_value).

        Args:
            new_value: The value string to display.

        Returns:
            tuple: (success: bool, error_message: str or None)
        """
        if self.icon_type != "live_value":
            return False, (
                f"key '{self.label}' (type={self.icon_type}) "
                f"does not accept value notifications"
            )
        self._value = str(new_value)
        self._enqueue_render()
        return True, None

    def update_poll_value(self, value):
        """Update live_value from polling. Same as notify_value but for internal use."""
        if self.icon_type == "live_value":
            self._value = str(value)
            self._enqueue_render()

    def restore_state(self, persisted):
        """Restore state from persisted data (loaded at startup).

        Args:
            persisted: dict with 'state' and/or 'value' keys.
        """
        if "state" in persisted:
            if self.icon_type == "toggle" and persisted["state"] in ("on", "off"):
                self._state = persisted["state"]
            elif self.icon_type == "multistate" and persisted["state"] in self._states:
                self._state = persisted["state"]
        if "value" in persisted and self.icon_type == "live_value":
            self._value = str(persisted["value"])

    def get_render_info(self):
        """Get the information needed to render this key.

        Returns:
            dict with keys: position, icon_type, icon_path, overlay_text, live_config
        """
        info = {
            "position": self.position,
            "icon_type": self.icon_type,
            "label": self.label,
        }

        icons = self.config.get("icons", {})

        if self.icon_type == "static":
            info["icon_path"] = icons.get("default")
        elif self.icon_type == "toggle":
            info["icon_path"] = icons.get(self._state)
        elif self.icon_type == "multistate":
            info["icon_path"] = icons.get(self._state)
        elif self.icon_type == "live_value":
            info["icon_path"] = icons.get("base")
            live = self._live_config
            fmt = live.get("format", "{value}")
            try:
                # Attempt float conversion for numeric format specs like {value:.1f}
                try:
                    typed_value = float(self._value)
                except (ValueError, TypeError):
                    typed_value = self._value
                info["overlay_text"] = fmt.format(value=typed_value)
            except (ValueError, KeyError):
                info["overlay_text"] = str(self._value)
            info["live_config"] = live

        return info

    def _enqueue_render(self):
        """Enqueue a render job for this key."""
        try:
            self.render_queue.put_nowait(self.get_render_info())
        except queue.Full:
            logger.warning("Render queue full, dropping render for key '%s'", self.label)


class KeyManager:
    """Manages all KeyState instances, dispatches presses and notifications."""

    def __init__(self, keys_config, render_queue):
        self._keys_by_position = {}
        self._keys_by_notification_id = {}
        self.render_queue = render_queue

        for key_cfg in keys_config:
            ks = KeyState(key_cfg, render_queue)
            self._keys_by_position[ks.position] = ks
            if ks.notification_id:
                self._keys_by_notification_id[ks.notification_id] = ks

    def get_key(self, position):
        """Get KeyState by (row, col) position."""
        return self._keys_by_position.get(tuple(position))

    def get_key_by_notification_id(self, notification_id):
        """Get KeyState by notification_id."""
        return self._keys_by_notification_id.get(notification_id)

    def handle_press(self, position):
        """Handle a key press at the given position.

        Returns:
            tuple: (key_state, new_state, action_config) or None if no key at position.
        """
        ks = self.get_key(position)
        if ks is None:
            logger.debug("No key configured at position %s", position)
            return None
        new_state, action = ks.press()
        logger.info("Key press: '%s' at %s → state=%s", ks.label, position, new_state)
        return ks, new_state, action

    def handle_notification(self, notification_id, state=None, value=None):
        """Handle an external notification.

        Args:
            notification_id: The dotted notification ID.
            state: New state (for toggle/multistate).
            value: New value (for live_value).

        Returns:
            tuple: (success: bool, error_message: str or None)
        """
        ks = self.get_key_by_notification_id(notification_id)
        if ks is None:
            return False, f"unknown notification_id: {notification_id}"

        if state is not None:
            return ks.notify_state(state)
        elif value is not None:
            return ks.notify_value(value)
        else:
            return False, "notification must include 'state' or 'value'"

    def restore_states(self, persisted_data):
        """Restore all key states from persisted data.

        Args:
            persisted_data: dict mapping notification_id → {state/value}.
        """
        for nid, data in persisted_data.items():
            ks = self.get_key_by_notification_id(nid)
            if ks:
                ks.restore_state(data)
                logger.debug("Restored state for '%s': %s", ks.label, data)

    def all_keys(self):
        """Return all KeyState instances."""
        return list(self._keys_by_position.values())

    def enqueue_all_renders(self):
        """Enqueue render jobs for all keys (used on initial draw)."""
        for ks in self._keys_by_position.values():
            ks._enqueue_render()

    def get_persist_data(self):
        """Get data suitable for state persistence.

        Returns:
            dict mapping notification_id → {state/value}.
        """
        data = {}
        for nid, ks in self._keys_by_notification_id.items():
            if ks.icon_type in ("toggle", "multistate"):
                data[nid] = {"state": ks.state}
            elif ks.icon_type == "live_value" and ks.value:
                data[nid] = {"value": ks.value}
        return data
