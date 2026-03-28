# streamdeck-ctrl

Headless, config-driven daemon for controlling an Elgato Stream Deck on Linux systems with no desktop environment. All behaviour — key layout, icons, actions, states — is declared in a single JSON configuration file. External services can push state changes via a Unix domain socket.

![Stream Deck in action](images/streamdeck-screenshot.png)
<!-- Replace with actual screenshot when available -->

## Features

- **Zero desktop dependency** — runs on framebuffer-only or fully headless systems
- **Fully declarative** — swap the JSON config to change the entire control panel
- **4 key types** — static, toggle, multistate, live_value (with text overlay)
- **Shell-scriptable notifications** — push state via `socat` or plain `write()` to a Unix socket
- **State persistence** — survives crashes and reboots, restores last known state
- **USB resilient** — auto-reconnect on disconnect, udev-triggered service start
- **Simulate mode** — full daemon testing without hardware (`--simulate`)
- **Buildroot-friendly** — pure Python, no compiled extensions beyond `hidapi`

## Hardware

- Raspberry Pi 4 (or any Linux system with USB)
- Elgato Stream Deck 15-key (5×3 grid, 72×72 pixel keys)
- Pi OS Lite (Bookworm) or Buildroot-based embedded Linux

## Quick Start

```bash
ssh pi@<pi-ip>
cd /home/pi
git clone https://github.com/hackboxguy/streamdeck-ctrl.git
cd streamdeck-ctrl
sudo ./setup.sh --config=./screens/display-control/display-control.json
```

`setup.sh` will:
1. Install system and Python packages via `apt`
2. Resolve `{INSTALL_DIR}` placeholders in the config
3. Install udev rule (auto-starts service when Stream Deck is present at boot)
4. Generate and install systemd service

The service starts only when a Stream Deck is detected at boot. No Stream Deck = no service running.

To uninstall:
```bash
sudo ./uninstall.sh
```

## Key Types

### `static`
Fixed icon. Press fires the action. No state tracked.
Use for: reboot, brightness step, one-shot commands.

### `toggle`
Two states: `on` / `off`, each with its own icon. Press alternates between states. Notifications can jump to either state.
Use for: enable/disable features, mute/unmute.

### `multistate`
N named states (3+), each with its own icon. Press cycles through in order, wrapping at the end. Notifications can jump to any state.
Use for: display mode (SDR/HDR/Night), fan speed, log level.

### `live_value`
Base icon with a runtime text overlay. Value updated by polling a script, Unix socket notification, or both.
Use for: sensor readouts, brightness %, status strings.

## Configuration

A config file declares the device settings, notification socket, and key layout. Icon paths are resolved relative to the config file's directory.

### Minimal Example

```json
{
  "device": {
    "brightness": 80
  },
  "keys": [
    {
      "position": [0, 0],
      "label": "Reboot",
      "icon_type": "static",
      "icons": { "default": "reboot.bmp" },
      "action": {
        "on_press": {
          "type": "script",
          "command": "/usr/sbin/reboot",
          "async": true
        }
      }
    }
  ]
}
```

### Full Structure

```json
{
  "device": {
    "brightness": 80,
    "reconnect_timeout_sec": 0,
    "reconnect_interval_sec": 2
  },
  "notification": {
    "type": "unix_socket",
    "socket_path": "/run/streamdeck-ctrl/notify.sock",
    "state_persist_path": "/path/to/state.json"
  },
  "keys": [ ... ]
}
```

| Field | Default | Description |
|---|---|---|
| `device.brightness` | `80` | Key backlight brightness (0–100) |
| `device.reconnect_timeout_sec` | `30` | Give up reconnecting after N seconds (0 = forever) |
| `device.reconnect_interval_sec` | `2` | Interval between reconnect attempts |
| `notification.socket_path` | `/run/streamdeck-ctrl/notify.sock` | Unix domain socket path |
| `notification.state_persist_path` | `/run/streamdeck-ctrl/state.json` | Runtime state file |

### Key Fields

| Field | Required | Description |
|---|---|---|
| `position` | yes | `[row, col]` — zero-indexed. Row 0–2, Col 0–4 for 15-key deck |
| `label` | yes | Human-readable name (used in logs and dry-run) |
| `icon_type` | yes | `static`, `toggle`, `multistate`, or `live_value` |
| `notification_id` | no | Dot-separated ID for external state/value updates |
| `action` | no | Action to execute on key press (see below) |

### Actions

```json
"action": {
  "on_press": {
    "type": "script",
    "command": "/path/to/script.sh {state}",
    "async": true
  }
}
```

```json
"action": {
  "on_press": {
    "type": "http",
    "method": "POST",
    "url": "http://localhost:8080/api/endpoint",
    "body": { "mode": "{state}" },
    "timeout_sec": 5,
    "async": true
  }
}
```

**Token substitution** — replaced at execution time:

| Token | Expands to |
|---|---|
| `{state}` | Current state (`on`, `off`, `hdr`, etc.) |
| `{value}` | Current live value string |
| `{label}` | Key label |
| `{key_pos}` | `row,col` (e.g. `0,2`) |

### `{INSTALL_DIR}` Placeholder

Use `{INSTALL_DIR}` in script paths and `state_persist_path` to keep configs portable. `setup.sh` replaces it with the repo's absolute path at install time:

```json
"command": "{INSTALL_DIR}/screens/display-control/scripts/brightness-up.sh"
```

After `setup.sh` on a Pi:
```json
"command": "/home/pi/streamdeck-ctrl/screens/display-control/scripts/brightness-up.sh"
```

To restore placeholders after changes: `git checkout -- <config-file>`

## Real-World Example: Display Control

The included `screens/display-control/` layout integrates with [als-dimmer](https://github.com/hackboxguy/als-dimmer) for display brightness and feature control:

![Display Control Layout](images/display-control-screenshot.png)
<!-- Replace with actual screenshot when available -->

```
Row 0:  [0,0] Brightness Up   [0,1] Brightness Down   [0,2] Video Loop   [0,3] ALS Adaptive   [0,4] Local Dimming
             (static)              (static)              (toggle)           (toggle)             (toggle)
```

**Brightness Up/Down** — reads current brightness via `als-dimmer-client --brightness`, adjusts by ±10%, and sets the new value. Avoids stale jumps when brightness was changed externally.

```bash
# brightness-up.sh
ALS_CLIENT="/home/pi/als-dimmer/bin/als-dimmer-client"
CURRENT=$("$ALS_CLIENT" --brightness)
NEW=$(( CURRENT + 10 ))
[ "$NEW" -gt 100 ] && NEW=100
"$ALS_CLIENT" --brightness=$NEW
```

**ALS Adaptive** — toggles between auto and manual mode:

```bash
# als-adaptive-toggle.sh — receives {state} as $1
if [ "$1" = "on" ]; then
    "$ALS_CLIENT" --mode=auto
else
    "$ALS_CLIENT" --mode=manual
fi
```

## Notification Protocol

The daemon listens on a Unix domain socket for newline-terminated JSON messages.

**Set toggle/multistate state:**
```bash
echo '{"id":"display.local_dimming","state":"on"}' \
  | socat - UNIX-CONNECT:/run/streamdeck-ctrl/notify.sock
```

**Push live value:**
```bash
echo '{"id":"sensor.temp","value":"53.2"}' \
  | socat - UNIX-CONNECT:/run/streamdeck-ctrl/notify.sock
```

**Multiple updates in one connection:**
```bash
(
  echo '{"id":"display.local_dimming","state":"on"}'
  echo '{"id":"sensor.temp","value":"61.3"}'
) | socat - UNIX-CONNECT:/run/streamdeck-ctrl/notify.sock
```

**Response format:**
```json
{"status": "ok"}
{"status": "error", "reason": "unknown notification_id: foo.bar"}
```

## CLI Reference

```
Usage: streamdeck-ctrl [OPTIONS]

Options:
  --config PATH        Path to JSON layout config file [required]
  --socket-path PATH   Override Unix socket path from config
  --brightness INT     Override brightness (0-100) from config
  --dry-run            Validate config and print key layout, do not open deck
  --simulate           Run full daemon with simulated deck (no hardware)
  --daemon             Fork to background (for non-systemd environments)
  --log-level LEVEL    debug | info | warning | error [default: info]
  --version            Print version and exit
```

**Validate a config:**
```bash
python3 streamdeck_ctrl/main.py --config ./screens/display-control/display-control.json --dry-run
```

**Test without hardware:**
```bash
python3 streamdeck_ctrl/main.py --config ./screens/display-control/display-control.json --simulate
```

## Creating a Screen

1. Create a directory under `screens/`:
   ```
   screens/my-screen/
   ├── my-screen.json          # Config file
   ├── icon-one.bmp            # 72×72 BMP icons
   ├── icon-two-on.bmp
   ├── icon-two-off.bmp
   └── scripts/
       ├── action-one.sh
       └── action-two.sh
   ```

2. Use `{INSTALL_DIR}` in script paths to keep the config portable.

3. Place raw source images in a `tmp/` subdirectory (git-ignored) and extract 72×72 BMP icons from them.

4. Validate with `--dry-run`, test with `--simulate`, deploy with `setup.sh`.

## Architecture

```
streamdeck_ctrl/
├── main.py            # CLI entry point, signal handling
├── daemon.py          # Deck lifecycle, reconnect loop, FakeDeck (simulate)
├── config.py          # JSON loader, schema validator, defaults
├── key_manager.py     # Per-key state machines (static/toggle/multistate/live_value)
├── action.py          # Script + HTTP execution, token substitution
├── notifier.py        # Unix socket server (selectors-based)
├── icon_renderer.py   # PIL rendering, text overlay, LRU cache
└── state_store.py     # Atomic JSON persistence
```

**Threading model:**

```
main thread ──→ key_callback ──→ event dispatch
                                      │
              ┌───────────────────────┼──────────────────┐
              │                       │                  │
        action_pool             render_thread       notifier_thread
        (ThreadPool)                  │              (Unix socket)
        script/http            PIL → set_key_image        │
                                      ▲                   │
                               poll_thread(s)             │
                               (live_value keys)          │
```

All `deck.set_key_image()` calls are serialized through `render_thread` — the Stream Deck HID interface does not tolerate concurrent writes.

## Buildroot

For embedded Linux builds, see `buildroot/Config.in` and `buildroot/streamdeck-ctrl.mk`. Requires `python3`, `python-pillow`, `python-requests`, `python-streamdeck`, and `libhidapi`.

## Dependencies

**Pi OS (Bookworm)** — installed via `apt` by `setup.sh`:
```
python3-pil  python3-requests  python3-jsonschema  python3-elgato-streamdeck
libhidapi-hidraw0  libhidapi-libusb0  socat
```

**pip/venv** (non-Debian systems):
```
pip install streamdeck pillow requests jsonschema
```

## License

MIT — see [LICENSE](LICENSE).
