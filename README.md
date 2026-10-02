# Slither website bot

A Python 3.12+ application that opens **http://slither.com/io** in headed Chromium, joins through the site's client, steers with a baseline agent, and records observations and human input. Press **F8** to take over or return control to AI.

The default target is the real website. `--target fixture` selects the old local page for offline regression checks only. The website adapter is a guarded compatibility integration; live gameplay could not be verified from this sandbox because local DNS access is blocked and Chromium launch is restricted. It never substitutes the fixture when the website fails.

## Setup and run

From this directory, with uv installed:

```sh
uv python install 3.12           # only needed if Python 3.12 is unavailable
uv sync --locked               # runtime + development dependencies
uv run playwright install chromium
uv run slither-bot --nickname "My bot"  # real Slither website, headed Chromium
```

PyTorch is optional and is never imported by the baseline:

```sh
uv sync --extra ml
```

The repository was initialized with `uv init --package --name slither-bot --python 3.12 --vcs none`; do not initialize it again. `.python-version` selects 3.12, while `requires-python` permits 3.12+. `uv.lock` and installed project dependencies are now present. On this machine, use the newer Homebrew uv and writable cache paths if the default uv encounters sandbox errors:

```sh
export UV_CACHE_DIR=/tmp/slither-bot-uv-cache
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers"
/opt/homebrew/bin/uv sync --locked
/opt/homebrew/bin/uv run playwright install chromium
/opt/homebrew/bin/uv run slither-bot --nickname "My bot"
```

Keep `PLAYWRIGHT_BROWSERS_PATH` set for both installation and execution if you use it. See [VALIDATION.md](VALIDATION.md) for the actual validation results and blockers.

## CLI and configuration

```sh
uv run slither-bot --help
uv run slither-bot --agent random --seed 7 --hz 15 --episodes 3
uv run slither-bot --mode HUMAN --seconds 120
uv run slither-bot --target fixture --headless --episodes 2  # offline smoke check
uv run slither-bot --config config.example.json
```

`--target`, `--nickname`, `--runs-dir`, `--log-level`, `--mode`, `--agent`, `--hz`, `--episodes`, `--seconds`, and `--seed` override JSON configuration. Zero episodes/seconds means no corresponding run limit. Configuration is nested into `browser`, `runtime`, `training`, `reward`, and `keys`; omitted fields use defaults. The full resolved configuration is saved per run. Observation sectors default to 16, independently of the 32 action directions.

Default shortcuts use DOM `KeyboardEvent.code`:

| Key | Effect |
| --- | --- |
| F8 | Switch AI/HUMAN ownership |
| F9 | Toggle training permission; the baseline has no training implementation |
| F10 | Atomically save `checkpoints/latest.json` |
| F11 | Truncate the current episode and reconnect/restart the selected game |
| Escape | Shut down and flush storage |
| Space | Human boost; release it to stop boosting |

Move the pointer over the game to steer in HUMAN mode. The website uses Space for automation boost. The bridge tags automation events and suppresses an automation keyup from reaching the game when an observed human boost is still held. Use Space for recorded demonstrations; ArrowUp and left-click boost events remain in the raw stream and invalidate sampled boost labels. The offline fixture uses Shift for AI boost. Application shortcuts call `preventDefault` and stop propagation where the browser permits. Function keys can conflict with browser fullscreen/devtools and OS media shortcuts; use Fn or change bindings to codes such as `KeyM`, `KeyT`, `KeyC`, `KeyR`, and `Escape` in JSON. Focus must be on the page for it to receive shortcuts. F9 only grants permission: eligible training on the baseline logs `unsupported`, and calling its `train_step` raises `NotImplementedError`; no losses or learning are fabricated.

## Manual takeover verification

This controlled procedure uses `uv run slither-bot --target fixture`. Repeat the takeover, focus, and restart checks on the real website using `uv run slither-bot`; live boost uses Space rather than the fixture’s separate Shift input. Automated tests do not establish physical-input behavior.

1. Run `uv run slither-bot --target fixture`. Observe AI movement and occasional boost.
2. While AI boost is active, hold Space and press F8. Check that AI steering stops and Shift boost releases, while Space continues boosting. Move your physical mouse and confirm it steers the fixture.
3. Release Space, move the pointer, and leave it still briefly. Human input starts as unknown: a fresh pointer event plus a Space press/release establishes a recordable action. Check `transitions/human.jsonl` and `events.jsonl` afterward.
4. Press F8 to resume AI, then rapidly toggle it twice. The resumed AI must use a fresh observation; mixed intervals must have `action_quality: "unknown"` and `replay_eligible: false`.
5. Alt/Command-Tab away while AI boosts. Return and confirm the app remains HUMAN; press F8 explicitly to resume AI.
6. In both modes, wait for fixture death and confirm automatic restart. Try F11 and F10, then Escape. Verify one episode summary per ended episode and no stuck boost.

The page revokes ownership synchronously on a shortcut/focus event. The host also increments a generation and checks it before individual input dispatches, including between mouse movement and boost changes. A command already dispatched to Chromium cannot be recalled. OS scheduling, binding delivery, and browser latency prevent a zero-latency guarantee. Cleanup releases only the automation-owned key hold. Shared-key provenance depends on observed page events and the ledger; a physical key already held before the page gains focus cannot be reconstructed reliably.

## Observations, actions, and rewards

`Action(dx, dy, boost)` is a desired continuous screen direction: right is +x, down is +y. Magnitude does not set speed. It contains no browser coordinates. The codec has 64 IDs: `direction = id // 2`, `boost = bool(id % 2)`, angle `2*pi*direction/32`. Encoding selects the nearest direction, with exact half-sector ties clockwise. Zero vectors are valid abstract data but cannot be encoded or applied as steering; such browser actions are rejected.

Observation schema v1 uses clockwise sectors centered on angles `2*pi*i/N`, starting at right. `enemy_distance` and `boundary_distance` are normalized by the canvas CSS diagonal and clipped to [0,1]. On Slither, food density is the fraction of loaded food samples within one viewport diagonal in each sector. Enemy distance is the nearest loaded head/body sample in that sector, capped at one diagonal; a value of 1 means no closer sample. These are client-visible samples, not complete map knowledge. Boundary distance uses the client’s circular map geometry. Unavailable collections produce `null`. The offline fixture has illustrative food markers and no enemy extraction. `null` always means unavailable; zero is a measured zero. Missingness must be carried into future model inputs with explicit masks. Feature lengths and known nonfinite values are rejected. Heading is radians; speed is CSS pixels/second; size and score are the client’s displayed length units when its lookup tables are available (otherwise `null`). Website speed is estimated from successive world positions and the CSS scale; the first sample is `null`. Timestamps use host monotonic nanoseconds.

The website adapter projects world coordinates through the client camera and scale into viewport CSS pixels, including the canvas backing-size/CSS-size ratio and offsets. The fixture adapter converts its 800x500 drawing coordinates similarly. Mouse targets intersect a ray from the current player center with the canvas interior, preserving direction rather than clipping each axis. The input rectangle is clipped to the viewport; missing projection information suspends AI input.

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
| `adapter.py`, `slither_adapter.py`, `scripts/slither_adapter.js` | Adapter contract and real Slither lifecycle/state extraction |
| `fixture_adapter.py`, `fixtures/game.html` | Optional offline test fixture |
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

MENU, STARTING, RUNNING, DEAD, and UNKNOWN are handled explicitly. Recovery has bounded timeouts/retries. Unknown status, missing player position, stale observations, and stale generations suspend AI input. Confirmed DEAD states finalize once and automatically restart in either mode. Capture/input failures propagate after cleanup rather than continuing with stale data.

## Checks

After successful dependency installation:

```sh
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
RUN_BROWSER_TESTS=1 uv run pytest -m integration
uv run slither-bot --target fixture --headless --episodes 2
node tests/bridge.cjs
node tests/slither_adapter.cjs
```

The integration test launches real headless Chromium against the local file, checks steering/boost, automation takeover/release, score/size growth, death, and restart. Unit tests use fake browser components and require no Chromium. Their async scenarios each own an event loop, just like the CLI. pytest-asyncio is available for future async fixtures.

## Website compatibility and next stage

`SlitherAdapter` uses the website’s existing client connection and inputs, not a replacement game or a custom server. It selects `window.slither` / `slithers` or legacy `snake` / `snakes`, checks `playing`, and uses `connect()` to start or reconnect. Nickname entry and visible Play controls are discovered semantically. A new player object creates a new episode identity, including if it appears between observation and input dispatch. The canvas camera, food, and length tables are read only; the adapter does not change server state or zoom.

Client internals are undocumented and can change. The integration uses feature-detected names documented by the [Slither bot project](https://slitherio-bot.readthedocs.io/en/latest/game-variables.html) and used in a [published client integration](https://greasyfork.org/en/scripts/514745-slither-io-auto-play-bot-2025/code). These sources establish compatibility targets, not proof that the current site works here. Unknown feature values remain missing; unrecognized startup/state fails visibly. There is no visual fallback, anti-bot bypass, or support for frontend changes that hide those globals. Reloading the page during a run is unsupported; restart the application to recalibrate timestamps and ownership. Other server participants are controlled by the live service; the bot cannot verify which are human.

The deterministic/random baseline is basic and can die quickly against other players. The next stage is a PyTorch DQN Agent with missingness masks, 64 Q outputs, epsilon exploration, target updates, and truthful `.pt` checkpoints through the existing serialized model worker and trainer. Preserve termination versus truncation and AI-only evaluation rules.
