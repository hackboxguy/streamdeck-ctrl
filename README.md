# streamdeck-ctrl

Headless, config-driven daemon for controlling an Elgato Stream Deck on Linux systems with no desktop environment. All behaviour — key layout, icons, actions, states — is declared in a single JSON configuration file. External services can push state changes via a Unix domain socket.

## Features

- **Zero desktop dependency** — runs on framebuffer-only or fully headless systems
- **Fully declarative** — swap the JSON config to change the entire control panel
- **6 key types** — static, toggle, multistate, live_value (with text overlay), radio, task
- **Shell-scriptable notifications** — push state via `socat` or plain `write()` to a Unix socket
- **State persistence** — survives crashes and reboots, restores last known state
- **USB resilient** — auto-reconnect on disconnect, udev-triggered service start
- **Simulate mode** — full daemon testing without hardware (`--simulate`)
- **Buildroot-friendly** — pure Python, no compiled extensions beyond `hidapi`

## Hardware

- Raspberry Pi 4 (or any Linux system with USB)
- Elgato Stream Deck — 15-key (5×3), Mini (3×2), or XL (8×4). Set `device.layout` in config;
  see [Per-deck layouts](#per-deck-layouts) to ship one config per deck size.
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

### `live_value` text wrapping

A value wider than the key is split across lines, breaking after `.`, `:`, `-`
or `/` where it can and hard-breaking a long unbroken word where it cannot.
Short readouts are untouched. Without this an IPv4 at a legible font size runs
off both edges of the key.

### `radio`
Two states: `on` / `off`, each with its own icon. Unlike `toggle`, press does **not** cycle the state — it fires the action only. State is controlled entirely by external notifications. Useful for mutually-exclusive selections (radio groups) where a sync script pushes the current selection from an external source of truth.
Use for: HDMI timing profiles, display modes, exclusive configuration choices.

### `task`
A one-shot job with a visible outcome. Four states — `idle`, `running`, `success`, `failure` — all sharing **one** icon; the state is drawn as a coloured border around it rather than as a separate image per state. Press starts the job: the key jumps to `running` and its border blinks. Presses are ignored while it runs, so the job cannot be started twice. The script the key launches reports the outcome over the notification socket, which leaves the border solid green or solid red until the next press.

Use for: firmware flashing, backups, long-running maintenance jobs.

```json
{
  "position": [5, 0],
  "label": "983HH IOC Flash",
  "icon_type": "task",
  "icons": { "default": "983hh-ioc-flash.png" },
  "notification_id": "ioc.flash_983hh",
  "task": {
    "blink_interval_sec": 0.5,
    "border_width": 6,
    "colors": { "running": "#00FF00", "success": "#00FF00", "failure": "#FF0000" }
  },
  "action": {
    "on_press": {
      "type": "script",
      "command": "{INSTALL_DIR}/screens/display-control/scripts/flash-ioc.sh --id=ioc.flash_983hh --label=983HH --board=983hh --npj=983HH.npj --firmware=983HH_983_manager.bin",
      "async": true,
      "timeout_sec": 600
    }
  }
}
```

The launched script reports back the same way any other service does:

```bash
echo '{"id":"ioc.flash_983hh","state":"success"}' \
  | socat - UNIX-CONNECT:/run/streamdeck-ctrl/notify.sock
```

| `task` field | Default | Description |
|---|---|---|
| `blink_interval_sec` | `0.5` | Border blink period while `running` |
| `border_width` | `6` | Border thickness in pixels |
| `colors.running` | `#00FF00` | Blinking border while the job runs |
| `colors.success` | `#00FF00` | Solid border after a successful run |
| `colors.failure` | `#FF0000` | Solid border after a failed run |
| `colors.idle` | *(none)* | No border — the bare icon |
| `colors.available` | *(none)* | A fifth state, `available`: something to do (an update), e.g. a yellow border |
| `colors.confirm` | *(none)* | A sixth state, `confirm`: the job waits for an answer (a second press; list it in `press_states`). Its border blinks like `running` |
| `hold_sec` | *(none)* | Press-and-hold: the press only counts after this long; a bar fills across the key while it is held, and letting go early cancels |
| `press_states` | every state but `running` | The states in which a press starts the job (e.g. `["available", "failure"]`) |
| `grey_states` | *(none)* | The states drawn greyed out, e.g. `["idle"]` for "nothing to do" |

`icons` may carry a picture per task state besides `default` (e.g. `"confirm": "fpga-golden-confirm.png"`, the question the key asks); a state without one shows `default`.

A running job can show its progress: send a `value` of 0-100 (with or without `"state":"running"`)
and a bar is drawn across the bottom of the key; it goes when the state leaves `running`.

```bash
echo '{"id":"ota.fpga","state":"running","value":"42"}' | socat - UNIX-CONNECT:/run/streamdeck-ctrl/notify.sock
```

`notification_id` is **required**: without it the script has no way to report an outcome and the key would blink forever. Task state is deliberately *not* persisted — a restart returns the key to `idle` rather than restoring a stale result.

Set `action.on_press.timeout_sec` to cover the worst-case run time. Script actions default to 30 s, which is far too short for flashing an MCU.

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
| `device.layout` | `[3, 5]` | `[rows, cols]` — grid size. `[3,5]` for 15-key, `[2,3]` for Mini, `[4,8]` for XL |
| `device.reconnect_timeout_sec` | `30` | Give up reconnecting after N seconds (0 = forever) |
| `device.reconnect_interval_sec` | `2` | Interval between reconnect attempts |
| `device.nav_position` | `"bottom"` | Row of the page arrows when the keys need more than one page: `"bottom"` (bottom-left ◀, bottom-right ▶) or `"top"`; the keys fill the other slots row by row. A USB `streamdeck-buttons.json` may set it too |
| `notification.socket_path` | `/run/streamdeck-ctrl/notify.sock` | Unix domain socket path |
| `notification.state_persist_path` | `/run/streamdeck-ctrl/state.json` | Runtime state file |

### Key Fields

| Field | Required | Description |
|---|---|---|
| `position` | yes | `[row, col]` — zero-indexed, within `device.layout` bounds |
| `label` | yes | Human-readable name (used in logs and dry-run) |
| `icon_type` | yes | `static`, `toggle`, `multistate`, `live_value`, `radio`, or `task` |
| `notification_id` | no | Dot-separated ID for external state/value updates. Required for state persistence across restarts and socket notifications. |
| `enabled_when` | no | `{"key": "<notification_id>", "state": "<state>"}`: the key is usable only while that other key is in that state. Otherwise it is drawn greyed out (greyscale, dimmed; its own state still shows) and presses are ignored; it is redrawn whenever the other key changes (press, notification or state watch). |
| `state_watch` | no | For a toggle or radio with `notification_id`: polls a source and turns it into `on`/`off` — a JSON file's boolean (`json_key`), or a file's or a command's first word through `text_map`. See [Shared Toggle State](#shared-toggle-state). |
| `task` | no | For a `task` key: blink period, border width, and per-state border colours |
| `action` | no | Action to execute on key press (see below) |

### Shared Toggle State

Use `state_watch` when multiple local UIs control the same write-only device state. The action that changes hardware writes the JSON atomically; the Stream Deck polls it and renders the corresponding toggle state.

```json
"state_watch": {
  "path": ["/data/cluster/fpga-ldpc-state.json", "/tmp/fpga-ldpc-state.json"],
  "json_key": "local_dimming",
  "poll_interval_sec": 1,
  "default_state": "on"
}
```

| Field | Meaning |
|---|---|
| `path` | the file, or a list of candidates: the first whose directory exists is read (a board with `/data`, else `/tmp`) |
| `command` | instead of `path`: a shell command run every interval (`timeout_sec`, default 3); its output's first word is the value. A failing command leaves the key as it is |
| `json_key` | the file is JSON: this boolean key is the state |
| `text_map` | the file's (or command's) first word through a map to `on`/`off` (a `task` key: to `idle`/`running`/`success`/`failure`); `"*"` maps every other word. A word the map does not know is ignored and logged once |
| `default_state` | the state while the file does not exist (default `off`) |

Keys that watch the same source at the same interval share one poller, so eight radio keys
that follow one command cost one run per interval. A radio key watched this way lights from
the source alone: the launcher's running app, for example
(`"command": "launcher-client … --command=get-running-app"`, `"text_map": {"cluster-v2-ev": "on", "*": "off"}`).

### Actions

```json
"action": {
  "on_press": {
    "type": "script",
    "command": "/path/to/script.sh {state}",
    "async": true,
    "timeout_sec": 30
  }
}
```

`timeout_sec` caps how long a script may run (default 30 s). Anything slower — a firmware flash, a backup — must raise it, or the daemon kills the script mid-run.

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

### Per-deck layouts

One service can drive different Stream Deck models. Next to the config passed with
`--config`, add a variant named `<name>-<cols>x<rows>.json`; when a deck of that size is
plugged in, the daemon loads the variant instead:

| Deck | File loaded for `--config=display-control.json` |
|---|---|
| Mini (3×2) | `display-control-3x2.json` if it exists |
| 15-key (5×3) | `display-control-5x3.json` if it exists, else `display-control.json` |

Give the variant its own `device.layout` (e.g. `[2, 3]`). The deck is checked at start-up;
if a deck needing another file is plugged in later, the daemon logs it and exits non-zero
so systemd (`Restart=on-failure`) restarts it with the matching file.

A deck **without** its own variant simply gets the loaded config's keys re-paginated for
its size, with navigation arrows — at start-up and live, when a deck of another size is
plugged in while the daemon runs (no restart; key states are kept). For example, the
68 keys of `display-control.json` span 6 pages on a 15-key deck. `setup.sh` resolves
`{INSTALL_DIR}` in the variants too. Keys that appear in both files should keep the same
`notification_id`, so state and scripts are shared.

### Button layout from a USB stick

At start-up the daemon looks for `streamdeck-buttons.json` at the top level of an
attached USB stick. If the file is there and is a valid **subset** of the `--config` file
(the superset), its keys are shown instead of the default ones; otherwise the default
config is used and the reason is logged (`journalctl -u streamdeck-ctrl | grep "USB override"`).

The file can only *pick* keys of the superset, never define or change one, so a stick
cannot add commands. Each entry of `keys` is a key's label, a key object copied
unchanged from the superset (its `position` is ignored; `{INSTALL_DIR}` and the
installed path count as the same), or `null` for an empty key (black, does nothing):

```json
{
  "keys": [
    "Home",
    "Local Dimming",
    "Pixel Compensation",
    null,
    "HDMI 27",
    { "label": "IP Address", "icon_type": "live_value", "...": "copied from the superset" }
  ]
}
```

- The deck fills its keys in the file's order, page by page (the last key of a page that
  has a next one is the ▶ arrow, the first of a page after the first is ◀); `null`
  entries leave keys empty, so a layout can put each key exactly where it wants. The same
  file works on any deck size (it re-flows in the same order); the per-deck variants
  (`*-3x2.json`) are not used while an override is active.
- A file is rejected if a key is unknown, listed twice, differs from the superset in
  any field, or is missing a key its `enabled_when` depends on (e.g. *Pixel
  Compensation* without *Local Dimming*). `device` and `notification` come from the
  superset, except `device.nav_position` (`"bottom"` or `"top"`, the row of the page
  arrows), which the file may set.
- An unmounted stick is mounted read-only through udisks2 just to read the file; one
  already mounted (e.g. `/media/pi/<LABEL>`) is read in place. The stick is only read at
  start-up (boot, deck replug, `systemctl restart streamdeck-ctrl`).
- Check a file on any PC before copying it to the stick:
  `python3 -m streamdeck_ctrl.main --config screens/display-control/display-control.json --check-buttons streamdeck-buttons.json`
- `--no-usb-override` turns the lookup off.

#### Layout builder (browser)

`tools/layout-builder/` turns the superset into one self-contained HTML page (keys,
icons and code inside; works offline in any browser, nothing to install). Users drag the
buttons they want onto any key of a preview of the deck (adding pages as they like),
which pages exactly as the daemon will, and download `streamdeck-buttons.json` for the
stick, with `null` gaps where keys are left empty. The *Arrows* list puts the page
arrows on the bottom (default) or the top row; switching it, or adding and removing
pages, keeps every key where it is (a key whose place becomes an arrow moves to the next
empty key). It refuses to download a layout
with a missing `enabled_when` partner, can import an existing file, and remembers the
draft in the browser.

```bash
python3 tools/layout-builder/make-layout-builder.py \
    --config screens/display-control/display-control.json \
    -o streamdeck-layout-builder.html
```

Re-run it whenever keys are added to the superset; the page picks keys by label. The
downloaded file carries a `_layout_builder` note (superset name and hash, deck size) that
the daemon ignores.

## Real-World Example: Display Control

The included `screens/display-control/` is micropanel's screen, six pages on a 15-key deck:

| Page | Keys |
|---|---|
| 1 | Home, Media Player, Slideshow, Default Ref Video, Display Settings, Brightness Up/Down, ALS Adaptive, Cluster Demo (the modern cluster: Legacy theme, DMS panel off, map on), IP Address, Display Power (on/off), Local Dimming, Pixel Compensation |
| 2 | the thirteen HDMI timing radios (12.3 NQ1, 15.6 2K5, 14.6 FHD DD, EDID, 12.3 NQ5, 14.6 2K5, 17.3 3K, 17.3 OTS-OLED, 3×QVue, 12.3 NQ1v1.1, 27", 14.6 FHD EJ, 17" IB-OLED) |
| 3 | Cluster Demo V2: the themes Legacy, EV, Harman, Horizon (fable1), Tiles, Atelier, Neo, Auto; Map, Camera, DMS; Stop; DMS Link |
| 4 | the five FPGA flash tasks (12.3-NQ5, 15.6-0OD, 14.6-EJ: `14-6-fhd-ej-new.bin`, 14.6-DD: `14-6-fhd-new.bin`, 12.3-NQ11: `12-3-nq1v11.bit`, Lattice) on the top row, the four IOC flash tasks and the OLED-IB touch flash task below them, and the Qvue-Legacy / Qvue-New IOC flash and Qvue-New FPGA flash tasks on the bottom row (after ←) |
| 5 | the SDR/HDR10+ demo clip keys and the Player keys (Stop, -10s, Pause, +10s; Loop in Blank 8's place), Dual Video (in Blank 9's place), then Blank 10-13 |
| 6 | Qvue-Legacy/FPGA-Flash, OTA-IOC, OTA-983, OTA-FPGA, OTA-System; Sync Video (row 2, column 1) |

The paginator has no page break: a last page holds up to 14 keys (13 + ←), so page 6 exists only while more than 14 keys follow page 4. Blank 8-13 fill page 5 to a full middle page and Blank 14 after the Qvue-Legacy FPGA key keeps the count above 14. Page 6's top row is full (the OTA keys took Blank 14-17's places), so Sync Video sits at row 2, column 1; a new page-6 key goes after Sync Video; a new page-5 key replaces one of Blank 8-13.

The arrows take one slot on each page (→ bottom right on all but the last, ← bottom left on
all but the first), so page 1 holds 14 keys, the middle pages 13 and the last up to 14; the
keys fill the free slots in list order.

**HDMI timing keys (page 2)** each run `scripts/apply-hdmi-<type>.sh`, which sets the Pi's
display type with micropanel's `pi-config-txt.sh --type=<type>` and reboots. On a 983HH with
every DIP switch off (983_manager v01.13 or later), that type is also what the RH850 runs:
micropanel's `dip-switch-resolution.sh` hands it over as the soft DIP at boot, so the keys are
the display selector of a rig without DIP settings. The lit key is the type the Pi runs
(`scripts/sync-hdmi-timing.sh`, whose type -> `notification_id` map must name every timing
key; a test checks this). The key images are 72×72; `images/make-hdmi-timing-icon.py` makes
the 12.3 NQ1v1.1, 27", 14.6 DD, 14.6 EJ and 17" IB-OLED pairs from the 12.3 NQ5 art.

The two 14.6" FHD keys are the same board and timing: **DD** (`14.6-fhd`, direct-drive
backlight) and **EJ** (`14.6-fhd-ej`, scan-mode backlight) differ only in their brightness
curve, so they differ only in the als-dimmer config the Pi picks. The DIP switch cannot tell
them apart, but the FPGA bitstream can (reg `0x10` byte 0: `0x00` DD, `0x01` EJ), and
`dip-switch-resolution.sh` switches a 14.6-fhd* type to the variant the FPGA reports at every
boot. The keys matter when the FPGA cannot be read; otherwise a press that disagrees with the
flashed bitstream is undone at the next boot.

**Cluster Demo V2 (page 3)** works through the launcher and the cluster's own state files,
not through a systemd unit (that is the stand-alone board's `screens/qt-cluster-demo/`):

- a theme key starts the launcher's `cluster-v2-<theme>` tile (`scripts/cluster-theme.sh`),
  stopping whatever else runs first and waiting for the launcher's home. The key that is lit
  is the tile the launcher reports running (`state_watch` on `get-running-app`), so a tile
  started by touch, or the cluster's own exit, shows on the deck within a second;
- **Map**, **Camera** and **DMS** write the cluster's state files in `/data/cluster`
  (`scripts/cluster-state.sh`): `map-backdrop.state`, and `dms-video-view.state` — Camera
  switches `on` ↔ `off` (the camera box; nothing while the DMS panel is off), DMS switches
  the whole panel off (`none`) and back to the camera key's last choice. A running cluster
  follows its files at once; a stopped one starts that way. The keys light from the same
  files, so the cluster's own MAP and DMS buttons show on the deck too. On an image without
  `/data/cluster` (the single-slot image) the keys do nothing and say so in the log;
- **Stop** ends the running app (the launcher's home), as Home on page 1.

**Cluster Demo (page 1)** is the same modern cluster, set up as the old cluster looked
(`scripts/launch-cluster-demo.sh`): DMS off and Map on through `cluster-state.sh`, then the
analog (Legacy) theme through `cluster-theme.sh`. These are the shared switches, so they stay
that way for later themes until DMS (page 3) or the cluster's own button turns the panel back
on, with the camera choice it had. The old `cluster-demo` app is no longer started.
- **DMS Link** (a `task` key) makes `eth0` the DHCP server of the link to the FocusDrive Xavier,
  192.168.10.1/24 (the Xavier keeps its fixed 192.168.10.2) - what the Network app's Wired
  card does, for a rig with no touch panel (`scripts/dms-link.sh`, through br-wrapper's
  `net-ctl.sh wired-set --iface=eth0 --mode=server --ip=192.168.10.1 --prefix=24`, as root via
  `sudo -n`; the daemon runs as pi). The border blinks while it works and settles green when
  `eth0` serves, or red with the reason in the journal (`journalctl -t dms-link`). The DHCP
  guard probes the port first: on the Xavier's direct cable it finds nothing and the port
  serves; on a LAN with its own DHCP server it takes the port down and the key turns red -
  it never overrides that. With no cable the mode is saved and the key is green ("serving when
  a cable is connected"). A port that already serves is left alone, so pressing it again is
  harmless. The key also lights by itself (`state_watch` every 10 s on `dms-link.sh --state`,
  which reads `net-ctl.sh status --iface=eth0`): green on a rig set up earlier, red when the
  guard stopped the port. The setting is a NetworkManager profile on `/data`: it survives
  power cycles and updates; a factory reset makes `eth0` a DHCP client again (the key goes
  dark - press it again). The SOME/IP multicast route and the advertise address are not the
  key's business: `cluster-v2.sh` sets them at every cluster start.

The stand-alone screen's Video-1 / Video-2 keys are not on this page: micropanel has no
`cluster-video` unit (its videos are launcher tiles of their own).

**Display Power** (page 1, row 3, column 2): a toggle that switches the remote display on or off through its IOC: `scripts/display-power.sh on|off` runs `disptool --device=ioc --command=disppower --value=on|off` (0x66 `DISP_POWER` register 0x0200; the IOC switches the panel, the FPGA and the FPD-Link stay up) and confirms the result by reading the register back; the key follows the register (`display-power.sh state`, every 3 s), so a change made elsewhere shows too. Only boards running `display_manager` (OTS-OLED, LAT45, S7, 3x QVue) have it: with anything else, or while a flash key holds `/tmp/target-flash.lock`, the press is refused and the icon goes back. Only 0x66 is used (a read of 0x32 hangs the stock QVue firmware). Icons: `images/make-display-power-icon.py`.

**OTA keys (page 6, top row)**: OTA-IOC, OTA-983, OTA-FPGA and OTA-System update the display IOC, the 983HH serializer board, the QVue FPGA and the SD card's system image in the field, with the same tools and rules as the System Manager app (br-wrapper `system-manager-app`), so the two never disagree. Each key is **grey** when there is nothing to do, **yellow** when an update is available, then **blinks green with a progress bar** while it runs and ends **green** or **red**. A press only counts after a **1.5 s hold** (a bar fills while held; letting go early cancels), and only on a yellow or red key.

| Key | Available when | Update | After |
|---|---|---|---|
| OTA-IOC | `update-iocs.sh --check` says the display IOC is `outdated` against the shipped `_ota.bin` | QVue running display_manager: `update-iocs.sh --qvue A --qvue-b B --warm`; other displays: `--ots A --ots-b B --keep-stream` | QVue: nothing (warm). Others: power cycle (`/tmp/micropanel-notice`) |
| OTA-983 | the same check says the 983HH board is `outdated` | `update-iocs.sh --983 A --983-b B` | power cycle (`/tmp/micropanel-notice`) |
| OTA-FPGA | QVue with `display_manager` v01.03+: the running image (`fpgaident`, link 0x01) differs from `version:` of `3xqvue-update.bin` in sp6bins' `manifest.txt`, **or no pixelpipe image answers** (link 0x00 for 30 s, 0x02, 0xFF: the vendor image as delivered, or an FPGA that did not configure) | the flasher VM's Update FPGA flow, see below | nothing (als-dimmer re-applies LD / PC) |
| OTA-System | `system-image-scan.sh` finds exactly one signed `.mpupdate` of another version on a USB stick, and the running image is committed | `ab-update install usb` (progress from the engine's progress file) | the engine reboots into the new image |

The A / B images are the ones `--check` names (`image=`, plus its `_otaB` sibling); nothing is installed that the check does not call outdated, so an image that was rolled back before (`update-iocs.sh` exit 5) is never offered again. An update holds `/tmp/target-flash.lock` (every flash script and the deck's pollers stay off the bus: a second I2C user during an IOC update can wedge the Pi's controller) and System Manager's `/tmp/system-update.lock` (its pid inside), and a check never runs while either is held. `update-iocs.sh` stops als-dimmer itself; the FPGA path stops and restarts it. When the checks run: at deck start-up (`scripts/sync-ota.sh`, retried every 30 s until each board answers), after any wire flash key (`flash-ioc.sh`, `flash-qvue-fpga.sh` re-check once they release the lock), and for OTA-System whenever a USB stick comes or goes (`lsblk` every 3 s, no I2C). Logs: `/tmp/ota-check.log`, `/tmp/ota-update.log`. `OTA_FORCE=1` (bench only) lets the FPGA path rewrite an image that already runs. Icons: `images/make-ota-icons.py`.

**OTA-FPGA flow** (`ota-update.sh fpga`; the same as the flasher VM's Update FPGA, `run_fpga_update` / `install_golden_if_needed`). Units are delivered with the vendor bitstream at flash address 0, which never starts the UPDATE slot (no IPROG / WBSTAR), so an UPDATE-slot write alone never runs there: our GOLDEN 0xD7 (`3xqvue.bin`, which jumps to 0x400000) has to be put at 0 once (rh850-baremetal `docs/qvue-vendor-fpga-baseline.md`).

1. Precheck: `display_manager` v01.03+ (the golden arm; older: OTA-IOC first, release 1.24 = v01.10 recommended); link 0x00 is re-read for up to 30 s (just after an MCU restart).
2. A pixelpipe image with the OTA engine answers (link 0x01, GOLDEN included: the recovery after a bad slot): `write:3xqvue-update.bin,0x400000,engine`, display on; an engine session the write resumed is ended.
3. Otherwise the direct path: `fpgaflash abort` (an open session would be resumed in its own mode), `begin` (1 MHz; the time is I2C's either way). A begin that reads no flash ID (`flash id is not 9D 60 18`, disptool 99eb558+ adds what it read; FF FF FF = the flash does not answer) is closed again and reported: power-cycle the QVue fully and retry, then hardware / JTAG; nothing is offered or written.
4. In the open session `verify:3xqvue.bin,0x0` (MATCH = our GOLDEN), else `verify:3xqvue-legacy.bin,0x0` (vendor), else unknown (e.g. a cut GOLDEN write).
5. GOLDEN at 0: the UPDATE slot only. Vendor / unknown: the key turns **amber, blinking, "GOLDEN? Hold = Yes"** and waits 60 s; **holding it again** answers yes (the second run finds `/tmp/qvue-fpga-confirm.wait` with its key's id, leaves `/tmp/qvue-fpga-confirm.yes` and exits). Yes: `write:3xqvue.bin,0x0,golden`, then the UPDATE slot, in the same session (about 10 min, display off: keep the QVue powered; a power loss while GOLDEN is written leaves the FPGA dark until the key is run again, no JTAG needed). No answer: `abort`, nothing written, red. A GOLDEN that verifies is never rewritten (the owner rule: a field update writes GOLDEN only where 0 is not ours).
6. `end` must report DONE; then `fpgaident` must show link 0x01, not "the GOLDEN image is running" (the slot did not start), and the manifest's image byte (0xDC today).
7. A write that fails leaves the session open (display off, `PROGRAM_B` low) and the key red: keep power and hold it again; the rerun goes through the same flow and the address-0 check resumes correctly.

The progress bar: checks 0-4 %, GOLDEN 5-50 %, the slot 50-97 % (5-97 % without GOLDEN), the boot 97-100 %. After every FPGA run OTA-FPGA is checked again.

**Pixel Compensation** is greyed out and ignores presses while Local Dimming is off (`"enabled_when": {"key": "display.local_dimming", "state": "on"}`): pixel compensation has no effect without local dimming. Its own on/off still shows under the grey, and it comes back as it was when LD is switched on.

**Local Dimming / Pixel Compensation** keep the choice where every app with LD/PC buttons
keeps it (`scripts/fpga-ldpc-lib.sh`): `/data/cluster/fpga-ldpc-state.json`, else
`/tmp/fpga-ldpc-state.json`, and drive the FPGA through micropanel's `disptool` with the
apps' rule — the new register slave (`0x1E`) whenever it answers, the legacy registers
(`0x29`, `0x47`) only on an FPGA without it.

The Mini variant (`display-control-3x2.json`) is a page of its own, the SDR/HDR demo clip
keys and the Player keys with IP Address; it is unchanged.

The screen integrates bidirectionally with [als-dimmer](https://github.com/hackboxguy/als-dimmer) for display brightness and feature control. Key presses send commands to als-dimmer, and als-dimmer's callback script pushes state changes back to update the deck icons in real time:

```
Row 0:  [0,0] Brightness Up   [0,1] Brightness Down   [0,2] Video Loop   [0,3] ALS Adaptive   [0,4] Local Dimming
             (static)              (static)              (toggle)           (toggle)             (toggle)
```

**Brightness key** (page 1, row 2, column 2): a `live_value` key showing the brightness als-dimmer holds and, under it, the display's backlight temperature, e.g. `30%` over `32°C`. `scripts/brightness-value.sh` is polled every 2 s; the up/down keys and als-dimmer's `brightness_changed` callback push the same value at once. The temperature is the reading the disp-settings app shows: the display IOC's (`0x66`) rows `0x1000..0x1003` via `disptool --device=ioc --command=bltemp` (one atomic I2C write+read), which is the backlight unit's thermistor on QVUE_9090 `display_manager` v01.04+ and the main-PCB NTC before that. It is read at most every 10 s and cached in `/tmp/streamdeck-bltemp.cache`, only when the IOC's `App Name` is `display_manager` (OTS-OLED, LAT45, S7, 3x QVue), never while a flash script holds `/tmp/target-flash.lock`, and only `0x66` is ever read (a read of `0x32` hangs the stock QVue firmware). No answer, qvue_legacy, an uncalibrated sensor or a value outside -40..125 °C shows the brightness alone.

**Brightness Up/Down** — reads current brightness via `als-dimmer-client --brightness`, adjusts by ±10%, and sets the new value. Avoids stale jumps when brightness was changed externally.

```bash
# brightness-up.sh
ALS_CLIENT="/home/pi/als-dimmer/bin/als-dimmer-client"
CURRENT=$("$ALS_CLIENT" --brightness)
NEW=$(( CURRENT + 10 ))
[ "$NEW" -gt 100 ] && NEW=100
"$ALS_CLIENT" --brightness=$NEW
```

**IOC Flash keys**: four `task` keys on page 4 (the middle row, below the FPGA keys: 983HH, S7-9090, LAT45, OLED-OTS), plus Qvue-Legacy and Qvue-New on the bottom row, each reflashing one board's RH850 IOC:

| Key | Board | Firmware | NPJ |
|---|---|---|---|
| 983HH | `983hh` | `983HH_983_manager.bin` | `983HH.npj` |
| S7-9090 | `spartan7-9090` | `REMOTE_DISP_SPARTAN7_display_manager_s4.bin` | *(none)* |
| LAT45 | `lattice45-9090` | `REMOTE_DISP_display_manager.bin` | `LAT-ECP5.npj` |
| OLED-OTS | `lattice45-9090` | `REMOTE_DISP_OTS_display_manager.bin` | `LAT-ECP5.npj` |
| Qvue-Legacy | `qvue-9090` | `QVUE_9090_qvue_legacy.bin` | *(none, Bluebox only)* |
| Qvue-New | `qvue-9090` | `QVUE_9090_display_manager.bin` | *(none, Bluebox only)* |

All four run the same `scripts/flash-ioc.sh`, differing only in arguments, and it shells out to micropanel's `rh850-flash-auto.sh` — which picks the transport itself: an EEHB Bluebox dongle (USB `0403:a9a0`) when one is plugged into the Pi, otherwise the Pi's own GPIO/UART wiring. The operator attaches the dongle and presses a key; the border blinks green while flashing and settles on solid green or solid red.

**Qvue-Legacy/IOC-Flash key**: a fifth IOC key on page 4, on the bottom row right after ← (in Blank 5's place). It flashes the 3x QVue display driver's RH850 F1KM-S1 (R7F701684, rh850-tool profile `r7f701684`: 16 MHz, 1 MiB code flash) with the stock-compatible `qvue_legacy` firmware. The board has no Pi GPIO wiring or NPJ, so it needs the Bluebox; without one `rh850-flash-auto.sh` refuses and the key goes red. It also passes `--expect-app=qvue_legacy`: after the flasher's own read-back verify, `flash-ioc.sh` waits up to 20 s for `disptool --device=ioc --command=iocversion` to report `App Name : qvue_legacy` over 0x66, and turns the key green only when it does. It also passes `--require-vendor-fpga`: while `display_manager` reports FPGA link 0x01 (our pixelpipe image), it refuses, because qvue_legacy speaks the vendor SPI protocol that the pixelpipe images reject (brightness would be dead); press Qvue-Legacy/FPGA-Flash first. The flash erases and writes 0x0..0x7FFFF, not just the image: a wire image is bootloader + slot A with boot_seq 0, so a `display_manager` left in slot B by an earlier OTA would otherwise keep booting. The vendor's stock firmware at 0x80000 and up is left alone. A press takes about 40 s.

**Qvue-New/IOC-Flash key**: next to Qvue-Legacy (in Blank 6's place), the same flow for the 0x66 remote-display firmware: it wire-flashes `QVUE_9090_display_manager.bin` (bootloader + slot A, clearing slot B) and expects `App Name : display_manager`. The two QVue keys switch the board between its two firmwares.

**Order of the QVue keys.** Both FPGA keys need `display_manager` on the MCU, which does the SPI writes, so:

- to legacy: **Qvue-Legacy/FPGA-Flash first, then Qvue-Legacy/IOC-Flash** (the IOC key refuses while the pixelpipe FPGA still runs);
- to new: **Qvue-New/IOC-Flash first, then Qvue-New/FPGA-Flash** (the FPGA keys refuse unless `App Name` is `display_manager`).

Both QVue IOC keys stop als-dimmer for the flash and start it again afterwards, because it picks its QVue config (0x66 for `display_manager`, 0x32 for stock / qvue_legacy) only when it starts.

**Qvue-New/FPGA-Flash key**: the third QVue key (in Blank 7's place) writes the QVue FPGA's (XA7S25) SPI configuration flash *through the QVue's MCU over I2C*; the QVue has no JTAG path. It runs the OTA-FPGA flow above (`ota-update.sh fpga --id=fpga.flash_qvue_new --force`), with a 1.5 s hold like the OTA keys: `--force` also rewrites an UPDATE slot that is already current (by the engine when a pixelpipe image answers). GOLDEN is written only where address 0 is not ours, after the same "GOLDEN? Hold = Yes" question. It needs `display_manager` v01.03+ on the MCU (Qvue-New/IOC-Flash first). The expected image is the `version:` of `3xqvue-update.bin` in sp6bins' `manifest.txt` (0xDC today), so a new UPDATE release needs no key change. Log: `/tmp/ota-update.log`.

**Qvue-Legacy/FPGA-Flash key (page 6)**: the same script, back to the vendor FPGA image as the unit was delivered. It needs `display_manager` on the MCU like the key above (the MCU does the SPI writes), then: stop als-dimmer, `fpgaflash abort` (any open session), `begin` (1 MHz; a flash that does not answer is reported as on OTA-FPGA), `write:3xqvue-legacy.bin,0,golden`, `end`. That replaces GOLDEN 0xD7 at offset 0 with the vendor image; the 0xD8 left in the UPDATE slot is never used, because the vendor image does not jump there. Success means `end` reported DONE (so the FPGA did configure: link 0xFF alone would also be an FPGA that never configured) and `fpgaident` shows `FPGA link : 0xFF`, or `0x02` ("legacy vendor frame (shim)", display_manager v01.10+) (`--expect-link=0xFF`): `display_manager` has no PPSPI to the vendor image, and the panel runs at the vendor bitstream's own level (about 3,100 nits full white). The display is off for about 4.5 min. Pressing Qvue-New/FPGA-Flash goes back to the pixelpipe pair.

The script takes a single lock across every board, since they all program over the same port — a second flash started while one is running exits instead of colliding with it.

**OLED-IB Touch-Flash key** — a fifth `task` key on page 4, after OLED-OTS, reflashes the 17" OLED-IB's touch controller (Himax HX8530) from the Pi itself; no dongle and no RH850 involved. It runs `scripts/flash-touch.sh --firmware=<file>`, which takes the image from micropanel's sp6bins tree (`share/sp6bins/firmware/touch/`), copies it to `/lib/firmware` (RAM on the overlayroot) and hands its name to the `himax_oledib` driver (`echo t <file> > /proc/android_touch/debug`). The driver programs and CRC-checks the flash in about 25 s. On success the border goes solid green and the Pi reboots 5 s later; the driver switches touch sensing back on when it probes. On failure the border goes solid red, the Pi stays up, and `/tmp/touch-flash.log` has the driver's messages. The key refuses to run unless `himax_oledib` is loaded, so on any other display type it fails without touching anything. It shares the flash scripts' lock. A new image is a new file in sp6bins and a new `--firmware=` here.

**SDR vs HDR10+ demo keys** — page 5 starts the side-by-side comparison
stand from [sdr-hdr-shootout-demo](https://github.com/hackboxguy/sdr-hdr-shootout-demo):
Peru, HDR10+ Test and Harman start that clip on both players in sync (`radio` keys
`demo.<clip>`, lit by the demo's control script; each runs `scripts/sdr-hdr-demo.sh <clip>`,
a wrapper for the demo's `demo-ctl.sh`).

**Player keys** — Player Stop, Player -10s, Player Pause, Player +10s and Player Loop drive
whatever is playing, through `scripts/player-ctl.sh stop|seek -10|toggle|seek +10|loop toggle`. It asks the players
in `scripts/players.d/` in name order and drives the first that is active:

| File | Player | How |
|---|---|---|
| `10-sdr-hdr-sync.sh` | the SDR/HDR shoot-out (its `sdr-hdr-sync` unit runs) | `demo-ctl.sh pause` / `rew` / `fwd` / `stop`: synchronized freeze and 10 s seeks of Kodi and the Zidoo; first, so Kodi is never driven behind the sync's back |
| `20-dual-video-player.sh` | dual-video-player (USB Media, Dual Video) | its control socket `/tmp/dual-video-player.sock` (br-wrapper `micropanel-media-player`) |
| `30-mpv.sh` | mpv-based players (qt-mpv-wrapper) | mpv JSON IPC on `/tmp/mpv-socket` or any `/tmp/mpv-*.sock` with a file open |
| `40-kodi.sh` | Kodi (Media Player) | JSON-RPC on :8080; Stop ends playback, Kodi stays open |

Each file is an executable answering `active`, `status`, `pause`, `resume`, `toggle`,
`seek [+-]S`, `stop`, `loop on|off|toggle` and `loop-status`; a new player is a new file (an mpv-based one with its IPC socket
at `/tmp/mpv-*.sock` needs none). Player Pause is a `toggle` key (`player.pause`) whose
`state_watch` runs `player-ctl.sh status` every 2 s, so it is lit exactly while the player
is paused, whoever paused it; `player-ctl.sh` also sets it right after a press. Player Loop
(`player.loop`, `video-loop-*.bmp`) works the same way with `player-ctl.sh loop-status`:
it repeats the video on screen - Kodi's repeat one, mpv's `loop-file`, dual-video-player's
`loop` (playlist mode: the item on screen, an image stays; two-file mode: both files, on
by default, off = play to the end) - and is always lit for the shoot-out, which always loops. The
shoot-out's sync reports its frozen state on the same key. `player-ctl.sh status` /
`which` / `stop-all` help from a shell. On a 6-key Mini, `display-control-3x2.json` spreads
the same keys over two pages (with IP Address in place of Home): the clips, Player Stop and
IP with a -> key, then Player -10s, Player Pause, Player +10s, the <- key and Player Loop — see
[Per-deck layouts](#per-deck-layouts).

**Dual Video** — a `task` key (`app.dual_video`, `dual-video.png` from
`images/make-dual-video-icon.py`) that plays `dual-player-video-1.mp4` / `-2.mp4` from the
USB stick (its top folder or `Videos/`), one per HDMI output, through the launcher's
`dual-video` entry, so Home and the Player keys work on it. Its `state_watch` runs
`scripts/launch-dual-video.sh state` every 3 s, which asks the launcher's own
`dual-video.sh --check`: no stick or no pair → `missing` = `idle`, greyed out, presses
ignored (`grey_states`, `press_states`); the pair is there → `ready` = `available`, the bare
icon, a press starts it (the border blinks until the player answers on its control
socket); playing → `success`, a green border, presses ignored. A start that fails turns it
red until the next poll, with the reason in `journalctl -t dual-video-key`. Not on the
Mini (its pages are full); the layout builder can put it on any deck.

**Home** — `scripts/launch-home.sh`: `player-ctl.sh stop-all` stops every active player
(also ones the launcher did not start, such as the shoot-out's sync), then the launcher's
`stop-app` brings back its home screen.

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

### Receiving Events from External Services

External daemons can push state changes to streamdeck-ctrl via a callback script that writes to the notification socket. This enables the Stream Deck to reflect state changes made outside of the deck (e.g. via a display's touch screen or another API).

The pattern:
1. Configure the external service to call a script on state change
2. The script maps the event to a streamdeck-ctrl notification and sends it via `socat`

Example bridge script (`als-dimmer-notify.sh`):
```bash
#!/bin/bash
# Called by als-dimmer: $1=event_type $2=value
SOCK="/run/streamdeck-ctrl/notify.sock"
case "$1" in
    mode_changed)
        [ "$2" = "auto" ] && STATE="on" || STATE="off"
        echo "{\"id\":\"display.als_adaptive\",\"state\":\"$STATE\"}" \
            | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
        ;;
    brightness_changed)
        echo "{\"id\":\"display.brightness\",\"value\":\"$2\"}" \
            | socat - UNIX-CONNECT:"$SOCK" 2>/dev/null
        ;;
esac
```

This keeps both services fully decoupled — the external service doesn't know about streamdeck-ctrl, and streamdeck-ctrl doesn't know about the external service.

## Security

`streamdeck-ctrl` is designed for **trusted, single-operator environments** (e.g. a dedicated Pi appliance). Script actions use `shell=True` with token substitution, and the Unix socket accepts connections from any local process. This is intentional for ease of integration with shell scripts and local services.

A `streamdeck-buttons.json` on a USB stick can only select keys of the installed config; any key that differs from it is rejected (see *Button layout from a USB stick*).

Do not expose the notification socket to untrusted networks or allow untrusted users to modify config files or notification payloads.

## CLI Reference

```
Usage: streamdeck-ctrl [OPTIONS]

Options:
  --config PATH        Path to JSON layout config file [required]
  --socket-path PATH   Override Unix socket path from config
  --brightness INT     Override brightness (0-100) from config
  --dry-run            Validate config and print key layout, do not open deck
  --check-buttons FILE Check FILE as a USB streamdeck-buttons.json for --config, list its keys
  --no-usb-override    Do not look for streamdeck-buttons.json on a USB stick
  --simulate           Run full daemon with simulated deck (no hardware)
  --simulate-layout CxR Deck size for --simulate, e.g. 3x2 (default 5x3)
  --daemon             Fork to background (for non-systemd environments)
  --log-level LEVEL    debug | info | warning | error [default: info]
  --version            Print version and exit
```

**Validate a config:**
```bash
python3 -m streamdeck_ctrl.main --config ./screens/display-control/display-control.json --dry-run
```

**Test without hardware:**
```bash
python3 -m streamdeck_ctrl.main --config ./screens/display-control/display-control.json --simulate
# as a Stream Deck Mini (loads display-control-3x2.json):
python3 -m streamdeck_ctrl.main --config ./screens/display-control/display-control.json --simulate --simulate-layout 3x2
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
├── usb_override.py    # streamdeck-buttons.json from a USB stick (subset of the config)
├── key_manager.py     # Per-key state machines (static/toggle/multistate/live_value/radio/task)
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
                          poll/blink thread(s)           │
                        (live_value / task keys)           │
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
