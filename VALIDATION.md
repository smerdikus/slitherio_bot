# Website adapter update — 2026-10-02

The default application now targets `http://slither.com/io`; the local fixture is explicitly selected with `--target fixture`. Project dependencies and `uv.lock` are now present in the workspace.

Current checks using the installed Python 3.12 environment:

- `uv run --no-sync pytest -q`: **98 passed, 1 skipped** (opt-in Chromium integration).
- `uv run --no-sync mypy`: **passed**, including fixes for two earlier typing issues.
- Ruff lint/format: passed.
- `node tests/bridge.cjs`: passed, including shared Space-key cleanup on takeover.
- `node tests/slither_adapter.cjs`: passed for modern client-shaped state objects, projection, food/enemy sectors, missingness, death, and respawn rejection. This is an adapter logic test, not live website validation.
- The default-target construction and snapshot/speed conversion tests also pass.

Live validation remains blocked: `curl http://slither.com/io` fails with `Could not resolve host: slither.com`. The actual installed application was launched with `--headless --seconds 5 --episodes 1`, but Chromium build 1243 exited on `SIGTRAP` before navigation (`BrowserType.launch: TargetClosedError`, macOS power-notification error). No live multiplayer gameplay or physical-input takeover is claimed as tested.

The original delivery record below is historical; its missing-dependency, missing-lockfile, and unrun-mypy limitations no longer describe the current installed workspace.

---

# Delivery validation — 2026-10-02

The project code, fixture, configuration, tests, and documentation were created in the initially empty repository. No existing work was overwritten. Python 3.12.12 and the project `.venv` were initialized with uv.

## Passed

- Ruff 0.15.20 formatting and lint checks: 23 Python files formatted; no lint findings. Executed the existing cached Ruff binary through `uv run --no-sync`.
- Python 3.12 regression suite: **96 passed, 1 skipped** in the fallback test environment. Coverage includes all 64 codec round trips, validation, ownership changes during input dispatch, held-input cleanup, reward/missingness, replay filtering/capacity/sampling, serialization/checkpoints, human-state inference, episode boundaries, recovery limits, stale inference, and serialized model work.
- Standalone JavaScript bridge assertions (`node tests/bridge.cjs`): shortcuts, repeated keydown suppression, synchronous generation revocation, focus loss/refocus, command ledger matching/expiry, shutdown.
- Python syntax compilation and CLI `--help` using the uv-created Python 3.12 environment.

The Python tests were run using already-cached, pure-Python pytest/dependencies copied to `/tmp/slither-offline-tests`, without changing system packages:

```sh
PYTHONPATH=src:/tmp/slither-offline-tests \
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
UV_CACHE_DIR=/tmp/slither-bot-uv-cache \
/opt/homebrew/bin/uv run --no-sync python -m pytest -q
```

This is a fallback validation run, **not a successfully synced dependency environment**. pytest-asyncio was unavailable, so pytest emitted one `Unknown config option: asyncio_mode` warning. Test scenarios own their event loops and still ran. The integration test is opt-in and was skipped in that suite.

## Blocked / not verified

- Default `uv 0.9.8` could not use its normal cache due to `Operation not permitted`. With a writable cache it panicked in macOS `system-configuration` with `Attempted to create a NULL object`.
- `/opt/homebrew/bin/uv` avoided that panic, but `uv sync` failed fetching PyPI (`https://pypi.org/simple/mypy/`): DNS lookup failed. `curl` also could not resolve `pypi.org`. An offline lock attempt could not resolve the required packages. **No genuine `uv.lock` could be generated**, and no placeholder lock was written.
- `uv run --no-sync mypy src tests` failed with `Failed to spawn: mypy / No such file or directory`. **Static type checking has not passed or run to completion.** Its configuration and dependency declaration are present.
- `uv run --no-sync python -m playwright install chromium` failed because Playwright is not installed in the unsynced `.venv`.
- As a fallback, the machine's existing Playwright 1.49.1 under Python 3.11 attempted Chromium installation into the workspace `.browsers` directory. All three download endpoints failed with DNS `ENOTFOUND` (`playwright.azureedge.net`, `playwright-akamai.azureedge.net`, `playwright-verizon.azureedge.net`). This older installation is outside the declared project dependency environment.
- A separate launch of the actual application with the existing Python 3.11 / Playwright 1.49.1 and cached Chromium build 1148 failed **before loading the fixture**: `BrowserType.launch: TargetClosedError`; the browser process exited on `SIGTRAP`, with `ThermalStateObserverMac unable to register to power notifications. Result: 9` in its log. This does not verify browser behavior.
- **Headed interaction, automated Chromium smoke behavior, and physical mouse/keyboard takeover have not been verified.** Follow the README procedure on a machine where Chromium can launch.

## Complete validation when access is available

```sh
export UV_CACHE_DIR=/tmp/slither-bot-uv-cache
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.browsers"
/opt/homebrew/bin/uv sync
/opt/homebrew/bin/uv run playwright install chromium
/opt/homebrew/bin/uv run ruff format --check .
/opt/homebrew/bin/uv run ruff check .
/opt/homebrew/bin/uv run mypy
/opt/homebrew/bin/uv run pytest
RUN_BROWSER_TESTS=1 /opt/homebrew/bin/uv run pytest -m integration
/opt/homebrew/bin/uv run slither-bot
```

Commit the generated `uv.lock` after dependency resolution succeeds. Normal environments can use `uv` directly and omit the cache/browser path overrides.
