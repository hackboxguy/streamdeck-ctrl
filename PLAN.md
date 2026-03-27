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

- [x] Create `streamdeck_ctrl/key_manager.py` — KeyState + KeyManager, all 4 icon types, render queue, state persistence
- [x] Create `tests/test_key_manager.py` — 43 tests: all icon types, press/notify/restore, KeyManager dispatch
- [x] **Test:** `pytest tests/test_key_manager.py` — 43/43 passed
- [x] **Commit**

## Phase 4: State Store
> Runtime state persistence to/from JSON file

- [x] Create `streamdeck_ctrl/state_store.py` — atomic write (os.replace), thread-safe with Lock, auto-create parent dirs
- [x] Create `tests/test_state_store.py` — 14 tests: load/save, thread safety, edge cases
- [x] **Test:** `pytest tests/test_state_store.py` — 14/14 passed
- [x] **Commit**

## Phase 5: Action Executor
> Script and HTTP action execution with token substitution

- [x] Create `streamdeck_ctrl/action.py` — token substitution, subprocess scripts, requests HTTP, ThreadPoolExecutor async
- [x] Create `tests/test_action.py` — 22 tests: substitution, script/HTTP execution (mocked), async dispatch
- [x] **Test:** `pytest tests/test_action.py` — 22/22 passed
- [x] **Commit**

## Phase 6: Notifier (Unix Socket Server)
> Unix domain socket accept loop, JSON parse, dispatch to key_manager

- [x] Create `streamdeck_ctrl/notifier.py` — selectors-based accept loop, JSON line parsing, dispatch, response write-back, clean shutdown
- [x] Create `tests/test_notifier.py` — 10 tests: state/value notifications, errors, multi-message, multi-client
- [x] **Test:** `pytest tests/test_notifier.py` — 10/10 passed
- [x] **Commit**

## Phase 7: Daemon & Main Entry Point
> USB lifecycle, reconnect loop, key callback routing, CLI parsing, signal handling

- [x] Create `streamdeck_ctrl/daemon.py` — FakeDeck, StreamDeckDaemon, reconnect loop, render thread, poll threads, simulate mode
- [x] Create `streamdeck_ctrl/main.py` — argparse CLI, signal handlers, daemonize, dry_run
- [x] Create `tests/test_daemon.py` — 11 tests: FakeDeck, simulate start/stop/notifications/key press, dry_run
- [x] **Test:** `pytest tests/` — 151/151 passed (full suite)
- [x] **Commit**

## ~~Phase 8: Dry-Run & Simulate Modes~~ (merged into Phase 7)
> Dry-run and simulate were implemented directly in daemon.py/main.py and tested in test_daemon.py

## Phase 9: Integration Test with Example Config
> Full stack test using example config, simulate mode, and socket notifications

- [x] Create `tests/test_integration.py` — 10 tests: full stack with simulate mode, socket notifications, key presses, state persistence across restarts, render queue
- [x] **Test:** `pytest tests/test_integration.py` — 10/10 passed
- [x] **Commit**

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
