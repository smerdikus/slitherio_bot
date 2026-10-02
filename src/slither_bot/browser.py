"""Async Playwright ownership, input ledger, and snapshot capture on one event loop."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page, Playwright

from slither_bot.actions import mouse_target
from slither_bot.config import Config
from slither_bot.controller import InputController
from slither_bot.fixture_adapter import FixtureAdapter
from slither_bot.types import (
    Action,
    ActionReceipt,
    BrowserSnapshot,
    Command,
    GameStatus,
    InputEvent,
)

log = logging.getLogger(__name__)


class PlaywrightGameBrowser:
    def __init__(
        self, config: Config, controller: InputController, adapter: FixtureAdapter
    ) -> None:
        self.config = config
        self.controller = controller
        self.adapter = adapter
        self.page: Page | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._last: BrowserSnapshot | None = None
        self._lock = asyncio.Lock()
        self._boost_owned = False
        self._events: list[InputEvent] = []
        self._tasks: set[asyncio.Task[None]] = set()
        self._offset_ns: int | None = None
        self._uncertainty_ns = 0
        self._command_id = 0

    async def launch(self) -> None:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.browser.headless, timeout=self.config.browser.timeout_s * 1000
        )
        self.page = await self._browser.new_page(
            viewport={
                "width": self.config.browser.width,
                "height": self.config.browser.height,
            }
        )
        self.page.set_default_timeout(self.config.browser.timeout_s * 1000)
        await self.page.expose_binding("__slitherInput", self._on_event)
        state = self.controller.snapshot()
        config = {
            "keys": vars(self.config.keys),
            "generation": state.generation,
            "mode": state.mode,
        }
        script = (Path(__file__).parent / "scripts" / "input_bridge.js").read_text()
        await self.page.add_init_script(
            "window.__slitherBridgeConfig=" + json.dumps(config) + ";" + script
        )
        await self.page.goto(self.adapter.url)
        await self.adapter.configure(self.page)
        # Midpoint calibration; preserve RTT/2 as uncertainty instead of claiming exact alignment.
        before = time.monotonic_ns()
        page_ms: float = await self.page.evaluate("performance.now()")
        after = time.monotonic_ns()
        self._offset_ns = (before + after) // 2 - int(page_ms * 1_000_000)
        self._uncertainty_ns = (after - before) // 2
        self._events.append(
            InputEvent(
                "clock_sync",
                after,
                after,
                state.generation,
                "host",
                {
                    "offset_ns": self._offset_ns,
                    "uncertainty_ns": self._uncertainty_ns,
                },
            )
        )

    def _on_event(self, source: Any, raw: dict[str, Any]) -> None:
        now = time.monotonic_ns()
        timestamp = (
            int(raw["page_ms"] * 1_000_000) + self._offset_ns
            if self._offset_ns is not None
            else now
        )
        event = InputEvent(
            raw["kind"],
            timestamp,
            now,
            int(raw["generation"]),
            raw["origin"],
            {**raw["payload"], "page_ms": raw["page_ms"]},
            self._uncertainty_ns if self._offset_ns is not None else -1,
        )
        self._events.append(event)
        previous = self.controller.snapshot()
        if event.kind == "command":
            self.controller.handle(Command(event.payload["command"]))
        elif event.kind == "focus":
            if event.payload["focused"]:
                self.controller.focus_gained()
            else:
                self.controller.handle(Command.FOCUS_LOST)
        current = self.controller.snapshot()
        # State mutation above contains no await; queued actions immediately see the new generation.
        if current.generation != previous.generation:
            task = asyncio.create_task(self.release_owned_inputs())
            self._tasks.add(task)
            task.add_done_callback(self._release_done)

    def _release_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("Input release failed: %s", task.exception())
            self.controller.handle(Command.SHUTDOWN)

    def _owns(self, generation: int) -> bool:
        state = self.controller.snapshot()
        return state.owns_ai and state.generation == generation

    async def capture(self) -> BrowserSnapshot:
        if self.page is None:
            raise RuntimeError("Browser is not launched")
        # Capture-start timestamp conservatively includes extraction latency in freshness checks.
        result = await self.adapter.extract(self.page, time.monotonic_ns())
        if self.config.browser.screenshots:
            result = replace(result, screenshot=await self.page.screenshot())
        self._last = result
        return result

    async def start_episode(self) -> None:
        if self.page is None:
            raise RuntimeError("Browser is not launched")
        await self.release_owned_inputs()
        self._last = None
        await self.adapter.start(self.page)

    async def _claim(self, generation: int, kind: str, **payload: Any) -> bool:
        if self.page is None or not self._owns(generation):
            return False
        if self._last is None or self._last.game is None:
            return False
        if (time.monotonic_ns() - self._last.captured_at_ns) / 1e9 > (
            self.config.runtime.max_observation_age_s
        ):
            return False
        if not await self.adapter.input_available(self.page, self._last.game.instance_id):
            return False
        if not self._owns(generation):
            return False
        self._command_id += 1
        claimed: bool = await self.page.evaluate(
            "command => window.__slitherBridge.claim(command)",
            {"id": self._command_id, "kind": kind, "generation": generation, **payload},
        )
        fresh = (time.monotonic_ns() - self._last.captured_at_ns) / 1e9 <= (
            self.config.runtime.max_observation_age_s
        )
        return claimed and self._owns(generation) and fresh

    async def _finish_command(self) -> None:
        if self.page is not None:
            await self.page.evaluate("id => window.__slitherBridge.finish(id)", self._command_id)

    async def apply(self, action: Action, generation: int) -> ActionReceipt:
        start = time.monotonic_ns()
        moved, boosted = False, False
        reason: str | None = None
        async with self._lock:
            last, page = self._last, self.page
            if not self._owns(generation):
                reason = "stale_generation_or_no_ownership"
            elif (
                last is None
                or last.status != GameStatus.RUNNING
                or last.game is None
                or last.player_center is None
                or page is None
            ):
                reason = "unknown_game_or_position"
            elif (start - last.captured_at_ns) / 1e9 > self.config.runtime.max_observation_age_s:
                reason = "stale_observation"
            else:
                try:
                    x, y = mouse_target(action, last.player_center, last.game.canvas)
                    if await self._claim(generation, "pointer", x=x, y=y):
                        # Already dispatched commands cannot be recalled. Check again before boost.
                        await page.mouse.move(x, y)
                        moved = True
                        await self._finish_command()
                    if moved and await self._claim(generation, "boost", down=action.boost):
                        if action.boost and not self._boost_owned:
                            # Mark ownership before dispatch, so cancellation still triggers keyup.
                            self._boost_owned = True
                            await page.keyboard.down(self.adapter.boost_key)
                        elif not action.boost and self._boost_owned:
                            await page.keyboard.up(self.adapter.boost_key)
                            self._boost_owned = False
                        boosted = True
                        await self._finish_command()
                    if not moved or not boosted or not self._owns(generation):
                        reason = "ownership_changed_during_action"
                except ValueError as exc:
                    reason = str(exc)
        receipt = ActionReceipt(
            generation, start, time.monotonic_ns(), moved, boosted, reason is None, reason
        )
        self._events.append(
            InputEvent(
                "action_receipt",
                receipt.finished_at_ns,
                receipt.finished_at_ns,
                generation,
                "host",
                vars(receipt),
            )
        )
        if not receipt.accepted:
            await self.release_owned_inputs()
        return receipt

    async def release_owned_inputs(self) -> None:
        async with self._lock:
            if not self._boost_owned or self.page is None:
                return
            self._command_id += 1
            await self.page.evaluate(
                "command => window.__slitherBridge.claim(command)",
                {
                    "id": self._command_id,
                    "kind": "boost",
                    "down": False,
                    "cleanup": True,
                    "generation": self.controller.snapshot().generation,
                },
            )
            await self.page.keyboard.up(self.adapter.boost_key)
            self._boost_owned = False
            await self._finish_command()

    def drain_events(self) -> list[InputEvent]:
        events, self._events = self._events, []
        return events

    async def close(self) -> None:
        try:
            await self.release_owned_inputs()
        finally:
            try:
                if self._tasks:
                    await asyncio.gather(*self._tasks, return_exceptions=True)
                if self._browser is not None:
                    await self._browser.close()
            finally:
                if self._playwright is not None:
                    await self._playwright.stop()
                self.page = None
