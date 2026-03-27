# streamdeck-ctrl — Implementation Plan

**Status:** In Progress
**PRD:** [streamdeck-ctrl-prd.md](streamdeck-ctrl-prd.md)

---

## Principles

- Incremental: each phase produces working, testable code
- Commit after each phase passes its tests
- No hardware required: all phases testable via `--dry-run`, `--simulate`, and unit tests
- Action receives state **after** transition (PRD convention)

---

## Phase 1: Project Skeleton & Config Loader
> Foundation: repo structure, config loading, JSON schema validation

- [x] Create directory structure (`streamdeck_ctrl/`, `config/`, `icons/`, `tests/`, `buildroot/`)
- [x] Create `requirements.txt`
- [x] Create `streamdeck_ctrl/__init__.py` with version
- [x] Create `streamdeck_ctrl/config.py` — JSON loader, jsonschema validator, defaults injector, icon path resolver & validation
- [x] Derive JSON schema from PRD (embedded in `config.py`)
- [x] Create `config/example-layout.json` — fully annotated reference config from PRD
- [x] Create `tests/test_config.py` — 30 tests: valid configs, schema violations, semantic validation, file errors
- [x] **Test:** `pytest tests/test_config.py` — 30/30 passed
- [x] **Commit**

## Phase 2: Icon Renderer
> PIL-based image rendering for all 4 icon types, LRU cache

- [x] Bundle `fonts/DejaVuSans-Bold.ttf` in repo (693KB)
- [x] Create `streamdeck_ctrl/icon_renderer.py` — PNG load+scale, text overlay with shadow, LRU cache, font fallback chain
- [x] Create test PNG assets in `tests/fixtures/` (6 colored 72x72 squares)
- [x] Create `tests/test_icon_renderer.py` — 21 tests: rendering, text overlay, cache behavior, edge cases
- [x] **Test:** `pytest tests/test_icon_renderer.py` — 21/21 passed
- [x] **Commit**

## Phase 3: Key Manager (State Machines)
> Per-key state machines for all 4 icon types, render job enqueueing

- [ ] Create `streamdeck_ctrl/key_manager.py` — `KeyState` class per key, press→next-state transitions, notify→jump-to-state, enqueue render jobs to a `queue.Queue`
- [ ] Create `tests/test_key_manager.py` — static press, toggle cycle, multistate wrap-around, notify jump, invalid notify state rejected, live_value update
- [ ] **Test:** `pytest tests/test_key_manager.py`
- [ ] **Commit**

## Phase 4: State Store
> Runtime state persistence to/from JSON file

- [ ] Create `streamdeck_ctrl/state_store.py` — load persisted state, atomic write (`os.replace`), thread-safe with `threading.Lock`
- [ ] Create `tests/test_state_store.py` — save/load round-trip, atomic write (no partial file on crash), missing file returns empty, merge with initial_state
- [ ] **Test:** `pytest tests/test_state_store.py`
- [ ] **Commit**

## Phase 5: Action Executor
> Script and HTTP action execution with token substitution

- [ ] Create `streamdeck_ctrl/action.py` — `{state}`, `{value}`, `{label}`, `{key_pos}` substitution, `subprocess.Popen` for scripts, `requests` for HTTP, async via `ThreadPoolExecutor`
- [ ] Create `tests/test_action.py` — token substitution, script execution (mock subprocess), HTTP execution (mock requests), async behavior
- [ ] **Test:** `pytest tests/test_action.py`
- [ ] **Commit**

## Phase 6: Notifier (Unix Socket Server)
> Unix domain socket accept loop, JSON parse, dispatch to key_manager

- [ ] Create `streamdeck_ctrl/notifier.py` — `selectors`-based accept loop in own thread, JSON line parsing, dispatch to key_manager, response write-back, clean shutdown via event
- [ ] Create `tests/test_notifier.py` — connect and send state update, send value update, unknown id error, invalid state error, multiple messages per connection
- [ ] **Test:** `pytest tests/test_notifier.py`
- [ ] **Commit**

## Phase 7: Daemon & Main Entry Point
> USB lifecycle, reconnect loop, key callback routing, CLI parsing, signal handling

- [ ] Create `streamdeck_ctrl/daemon.py` — deck open/close, reconnect loop, key callback → key_manager, render_thread consuming render_queue → `deck.set_key_image()`, poll threads for live_value keys, simulate mode (log renders instead of HID)
- [ ] Create `streamdeck_ctrl/main.py` — argparse CLI (`--config`, `--socket-path`, `--brightness`, `--dry-run`, `--simulate`, `--log-level`, `--daemon`, `--version`), signal handlers (SIGTERM/SIGINT), daemonize double-fork, wire all modules
- [ ] Create `tests/test_daemon.py` — simulate mode startup/shutdown, key press routing, reconnect behavior (mocked deck)
- [ ] **Test:** `pytest tests/test_daemon.py`
- [ ] **Commit**

## Phase 8: Dry-Run & Simulate Modes
> End-to-end validation without hardware

- [ ] Implement `--dry-run` in `main.py` — load config, validate, print key layout table, verify icon files, exit
- [ ] Implement `--simulate` in `daemon.py` — full daemon loop with a `FakeDeck` class that logs image updates instead of HID writes
- [ ] Create `tests/test_dry_run.py` — dry-run output matches expected format
- [ ] Create `tests/test_simulate.py` — simulate mode processes key presses and notifications correctly
- [ ] **Test:** `pytest tests/test_dry_run.py tests/test_simulate.py`
- [ ] **Commit**

## Phase 9: Integration Test with Example Config
> Full stack test using example config, simulate mode, and socket notifications

- [ ] Create `tests/test_integration.py` — start daemon in simulate mode, send notifications via socket, verify state transitions and render calls
- [ ] Verify `--dry-run` with `config/example-layout.json`
- [ ] **Test:** `pytest tests/test_integration.py`
- [ ] **Commit**

## Phase 10: Deployment Artifacts
> setup.sh, uninstall.sh, systemd unit, udev rule, buildroot package

- [ ] Create `99-streamdeck.rules` (udev)
- [ ] Create `streamdeck-ctrl.service` (systemd unit)
- [ ] Create `setup.sh` — full installer per PRD section 8
- [ ] Create `uninstall.sh` — reverse of setup.sh
- [ ] Create `buildroot/Config.in` and `buildroot/streamdeck-ctrl.mk`
- [ ] **Test:** shellcheck `setup.sh` and `uninstall.sh`
- [ ] **Commit**

---

## Notes

- All phases can be tested on WSL2 (no Stream Deck hardware needed)
- `--simulate` mode is the key enabler for integration testing without hardware
- Thread safety: `state_store` protected by lock, `deck.set_key_image()` serialized through `render_queue`, notifier uses `selectors` for clean shutdown
- Font: DejaVuSans-Bold.ttf (~700KB) bundled in `fonts/` directory
