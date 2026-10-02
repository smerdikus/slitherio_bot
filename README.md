# Slither browser-control MVP

A modular Python 3.12+ foundation for observing and controlling a browser game, recording AI and human intervals, and adding a learning agent later. **The bundled moving-dot page is an input/lifecycle test fixture, not a realistic Slither simulator.** No real target URL, selectors, computer vision, or trained policy are included.

## Setup and run

From this directory, with uv installed:

```sh
uv python install 3.12           # only needed if Python 3.12 is unavailable
uv sync                        # runtime + development dependencies; generates uv.lock
uv run playwright install chromium
uv run slither-bot              # headed Chromium, deterministic baseline, local fixture
```

PyTorch is optional and is never imported by the baseline:

```sh
uv sync --extra ml
```

The repository was initialized with `uv init --package --name slither-bot --python 3.12 --vcs none`; do not initialize it again. `.python-version` selects 3.12, while `requires-python` permits 3.12+. After successfully generating `uv.lock`, commit it and use `uv sync --locked` for reproducible installations.

**Delivery environment limitation:** `.venv` was created, but the sandbox could not resolve PyPI hosts. Dependency sync and genuine `uv.lock` generation could not complete; no placeholder lockfile is provided. The installed default uv also panicked in macOS system-configuration access. `/opt/homebrew/bin/uv` avoided that panic but encountered the DNS restriction. On this machine, the commands below use writable cache/browser paths:

```sh
export UV_CACHE_DIR=/tmp/slither-bot-uv-cache
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers"
/opt/homebrew/bin/uv sync
/opt/homebrew/bin/uv run playwright install chromium
/opt/homebrew/bin/uv run slither-bot
```

Keep `PLAYWRIGHT_BROWSERS_PATH` set for both installation and execution if you use it. See [VALIDATION.md](VALIDATION.md) for the actual validation results and blockers.

## CLI and configuration

```sh
uv run slither-bot --help
uv run slither-bot --agent random --seed 7 --hz 15 --episodes 3
uv run slither-bot --mode HUMAN --seconds 120
uv run slither-bot --headless --episodes 2    # automated runs only
uv run slither-bot --config config.example.json
```

`--runs-dir`, `--log-level`, `--mode`, `--agent`, `--hz`, `--episodes`, `--seconds`, and `--seed` override JSON configuration. Zero episodes/seconds means no corresponding run limit. Configuration is nested into `browser`, `runtime`, `training`, `reward`, and `keys`; omitted fields use defaults. The full resolved configuration is saved per run. Observation sectors default to 16, independently of the 32 action directions.

Default shortcuts use DOM `KeyboardEvent.code`:

| Key | Effect |
| --- | --- |
| F8 | Switch AI/HUMAN ownership |
| F9 | Toggle training permission; the baseline has no training implementation |
| F10 | Atomically save `checkpoints/latest.json` |
| F11 | Truncate the current episode and restart the fixture |
| Escape | Shut down and flush storage |
| Space | Human boost; release it to stop boosting |

Move the pointer over the canvas to steer in HUMAN mode. The fixture reserves Shift for automation boost, allowing AI Shift release to preserve a physical Space hold. Shift should not be used as a human boost input. Application shortcuts call `preventDefault` and stop propagation where the browser permits. Function keys can conflict with browser fullscreen/devtools and OS media shortcuts; use Fn or change bindings to codes such as `KeyM`, `KeyT`, `KeyC`, `KeyR`, and `Escape` in JSON. Focus must be on the page for it to receive shortcuts. F9 only grants permission: eligible training on the baseline logs `unsupported`, and calling its `train_step` raises `NotImplementedError`; no losses or learning are fabricated.

## Manual takeover verification

This procedure requires a person using a headed browser; automated tests do not establish physical-input behavior.

1. Run `uv run slither-bot`. Observe AI movement and occasional boost.
2. While AI boost is active, hold Space and press F8. Check that AI steering stops and Shift boost releases, while Space continues boosting. Move your physical mouse and confirm it steers the fixture.
3. Release Space, move the pointer, and leave it still briefly. Human input starts as unknown: a fresh pointer event plus a Space press/release establishes a recordable action. Check `transitions/human.jsonl` and `events.jsonl` afterward.
4. Press F8 to resume AI, then rapidly toggle it twice. The resumed AI must use a fresh observation; mixed intervals must have `action_quality: "unknown"` and `replay_eligible: false`.
5. Alt/Command-Tab away while AI boosts. Return and confirm the app remains HUMAN; press F8 explicitly to resume AI.
6. In both modes, wait for fixture death and confirm automatic restart. Try F11 and F10, then Escape. Verify one episode summary per ended episode and no stuck boost.

The page revokes ownership synchronously on a shortcut/focus event. The host also increments a generation and checks it before individual input dispatches, including between mouse movement and boost changes. A command already dispatched to Chromium cannot be recalled. OS scheduling, binding delivery, and browser latency prevent a zero-latency guarantee. Cleanup releases only the automation-owned Shift hold. A real-game adapter with shared physical/automated keys needs its own explicit ownership policy.

## Observations, actions, and rewards

`Action(dx, dy, boost)` is a desired continuous screen direction: right is +x, down is +y. Magnitude does not set speed. It contains no browser coordinates. The codec has 64 IDs: `direction = id // 2`, `boost = bool(id % 2)`, angle `2*pi*direction/32`. Encoding selects the nearest direction, with exact half-sector ties clockwise. Zero vectors are valid abstract data but cannot be encoded or applied as steering; such browser actions are rejected.

Observation schema v1 uses clockwise sectors centered on angles `2*pi*i/N`, starting at right. `enemy_distance` and `boundary_distance` are normalized by the canvas CSS diagonal and clipped to [0,1]. Food density is a [0,1] fraction of fixture food markers in each angular sector. Markers are illustrative; fixture growth is driven by time. Enemy features are `null` because the fixture does not extract enemies. `null` always means unavailable; zero is a measured zero. Missingness must be carried into future model inputs with explicit masks. Feature lengths and known nonfinite values are rejected. Heading is radians; speed is CSS pixels/second; size and score are fixture-defined units. Timestamps use host monotonic nanoseconds.

The adapter converts the fixture's 800x500 drawing coordinates into viewport CSS pixels, including canvas offsets. Mouse targets intersect a ray from the current player center with the canvas interior, preserving direction rather than clipping each axis. The fixture uses fixed aspect ratio and an untransformed canvas.

Reward is centralized in `reward.py`:

```text
length_gain_weight * measured_size_delta
+ survival_reward_per_second * actual_interval_duration
- death_penalty * terminated
```

Growth contributes zero when either size measurement is missing. Each interval logs growth, survival, death, and `missing_size`. Episode reward includes intervals without usable action labels. Consequently an episode's reward can differ from the sum of its stored action transitions. Durations are measured between host captures, including normal dispatch/inference delay; receipts separately record dispatch timestamps. This is sampled control, not exact per-frame action reconstruction.

## Recording and checkpoints

Each run streams data into:

```text
runs/<UTC timestamp>-<unique suffix>/
  config.json
  episodes.csv
  training.csv
  events.jsonl
  transitions/
    ai.jsonl
    human.jsonl
  checkpoints/
    latest.json    # F10; baseline agent kind and PRNG state
    best.json      # best completed AI-only death episode in this run
```

No fake `.pt` files are written. `latest.pt`/`best.pt` are reserved for a future PyTorch agent. Baseline JSON writes use a temporary file, fsync, and atomic replacement. Human-assisted episodes cannot become `best.json`; this simple comparison is not a statistical policy evaluation. Loss and epsilon remain empty until an actual learner supplies them. Event and transition files are line-buffered; episode finalization flushes all streams, and cleanup closes them. Abrupt process termination can still leave an incomplete final line; readers should detect that rather than silently treating it as a complete record.

Each transition wrapper contains the typed transition, reward terms, and replay eligibility. Death terminates; requested restart, observed respawn, episode/run time limits, and shutdown truncate. A mode switch does neither. A changed fixture instance ends the old episode before any new state is admitted. Missing final observations are allowed on disk; ordinary nonterminal and truncated records without a next state cannot enter replay. Terminal death may omit its final observation. Rejected/partial actions produce receipts, not clean action transitions.

Human actions retain their continuous sampled direction and boost plus a nearest discrete ID labeled `quantized`. Unknown initial pointer/boost prevents inference of a label. Multiple input changes or ownership changes mark an interval `unknown`, exclude it from replay, and preserve raw events. Human demonstrations always go to a separate stream and are initially excluded from AI replay. Human directions are sampled relative to the moving player center, so fixed pointer targets can yield evolving steering between samples.

The bridge records pointer, boost, focus, shortcut, and automation ledger events. Browser `performance.now()` is calibrated against host monotonic time using a round-trip midpoint; calibration uncertainty and original page timing are recorded. Ledger matching uses command IDs, generations, event type, coordinates/key state, and a limited time window. `isTrusted` is only diagnostic. Playwright events can be trusted too. A coincident physical event matching a ledger command is inherently ambiguous; the ledger cannot prove physical provenance.

## Architecture

| Module | Responsibility |
| --- | --- |
| `types.py` | Standard-library dataclasses/enums and small Protocol interfaces |
| `actions.py` | Discrete codec and direction-to-CSS geometry |
| `browser.py`, `scripts/input_bridge.js` | Playwright lifecycle, generation checks, input ownership, raw events |
| `fixture_adapter.py`, `fixtures/game.html` | Isolated fixture URL, state extraction, startup, and boost channel |
| `observer.py` | Plain snapshots to validated observations; no Playwright handles |
| `controller.py` | Mode, generation, focus, commands, training permission |
| `human.py` | Explicitly unknown/known sampled human input state |
| `model.py` | Deterministic/random baselines; no browser automation or torch |
| `train.py` | One serialized model thread and configurable training schedule |
| `reward.py`, `replay.py` | Reward terms and bounded reproducible AI replay |
| `storage.py` | Streaming records and atomic JSON checkpoint helper |
| `app.py` | Episode lifecycle, interval attribution, recording, model orchestration |
| `config.py`, `main.py` | Nested configuration, CLI, and component construction |

Playwright stays on one owning asyncio loop. Prediction, training, and agent checkpoint work use one serialized worker so future native model calls cannot block input callbacks. Generation checks discard predictions that finish after a takeover. Training runs between control intervals and can reduce control frequency; the runtime does not issue catch-up bursts. A running native worker job cannot be forcibly cancelled; browser cleanup happens before waiting for worker shutdown.

MENU, STARTING, RUNNING, DEAD, and UNKNOWN are handled explicitly. Recovery has bounded timeouts/retries. Unknown status, missing player position, stale observations, and stale generations suspend AI input. Confirmed fixture DEAD states finalize once and automatically restart in either mode. Capture/input failures propagate after cleanup rather than continuing with stale data.

## Checks

After successful dependency installation:

```sh
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
RUN_BROWSER_TESTS=1 uv run pytest -m integration
uv run slither-bot --headless --episodes 2
```

The integration test launches real headless Chromium against the local file, checks steering/boost, automation takeover/release, score/size growth, death, and restart. Unit tests use fake browser components and require no Chromium. Their async scenarios each own an event loop, just like the CLI. pytest-asyncio is available for future async fixtures.

## Replace the fixture and next stage

Implement a real adapter beside `fixture_adapter.py` only after a real URL and extraction/input contract are supplied. Supply navigation/configuration, start behavior, a boost mapping with ownership semantics, and typed snapshot extraction. Ensure respawn identity changes reliably and terminal snapshots cannot be mistaken for a new life. Define real size/score units, sector measurements, canvas CSS geometry, focus behavior, and unknown values. Wire the adapter in `main.build`; update the browser's adapter type to a small Protocol if a second adapter requires it. Keep page handles inside the browser/adapter layer. For document navigation, reinstall/recalibrate the bridge and coordinate its generation with the host before restoring input. No real-site assumptions are embedded in the observer, agent, controller, or replay.

Next implement a PyTorch DQN `Agent` with observation/missingness vectorization, 64 Q outputs, epsilon exploration, target-network updates, and truthful `.pt` checkpoints; then extend the existing trainer schedule and evaluate on AI-only episodes. Preserve termination versus truncation when bootstrapping and route all model operations through `ModelWorker`. Full DQN/PPO/SAC, sophisticated vision, imitation learning, multiprocessing, and real-game integration are intentionally outside this MVP.
