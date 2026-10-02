from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from slither_bot.browser import PlaywrightGameBrowser
from slither_bot.config import Config
from slither_bot.controller import InputController
from slither_bot.fixture_adapter import FixtureAdapter
from slither_bot.types import Action, Command, ControlMode
from tests.helpers import async_case, snapshot

if TYPE_CHECKING:
    from playwright.async_api import Page


class FakePage:
    def __init__(self, on_move: Callable[[], None] | None = None) -> None:
        self.mouse = self
        self.keyboard = self
        self.on_move = on_move
        self.calls: list[str] = []
        self.fail_down = False

    async def evaluate(self, expression: str, arg: Any = None) -> bool:
        return True

    async def move(self, x: float, y: float) -> None:
        self.calls.append("move")
        if self.on_move:
            self.on_move()

    async def down(self, key: str) -> None:
        self.calls.append("down:" + key)
        if self.fail_down:
            raise RuntimeError("Injected dispatch failure")

    async def up(self, key: str) -> None:
        self.calls.append("up:" + key)


def browser_with_page(controller: InputController, page: FakePage) -> PlaywrightGameBrowser:
    browser = PlaywrightGameBrowser(Config(), controller, FixtureAdapter(4, 12))
    browser.page = cast("Page", page)
    browser._last = snapshot()
    return browser


@async_case
async def test_takeover_between_move_and_boost() -> None:
    controller = InputController()
    page = FakePage(lambda: controller.handle(Command.TOGGLE_MODE))
    browser = browser_with_page(controller, page)
    receipt = await browser.apply(Action(1, 0, True), 0)
    assert receipt.steering_applied and not receipt.boost_applied and not receipt.accepted
    assert page.calls == ["move"]
    assert controller.snapshot().mode == ControlMode.HUMAN
    assert not (await browser.apply(Action(0, 1, True), 0)).accepted
    assert page.calls == ["move"]


@async_case
async def test_held_input_cleanup_only_automation_and_focus_revocation() -> None:
    controller = InputController()
    page = FakePage()
    browser = browser_with_page(controller, page)
    assert (await browser.apply(Action(1, 0, True), 0)).accepted
    controller.handle(Command.FOCUS_LOST)
    await browser.release_owned_inputs()
    await browser.release_owned_inputs()
    assert page.calls == ["move", "down:Shift", "up:Shift"]
    controller.focus_gained()
    assert not controller.snapshot().owns_ai
    assert not (await browser.apply(Action(1, 0, True), 0)).accepted
    controller.handle(Command.TOGGLE_MODE)
    assert controller.snapshot().owns_ai
    assert not (await browser.apply(Action(1, 0), 0)).accepted


@async_case
async def test_cleanup_after_failed_keydown() -> None:
    import pytest

    controller = InputController()
    page = FakePage()
    page.fail_down = True
    browser = browser_with_page(controller, page)
    with pytest.raises(RuntimeError):
        await browser.apply(Action(1, 0, True), 0)
    await browser.close()
    assert page.calls[-1] == "up:Shift"


@async_case
async def test_host_bridge_revokes_before_async_release() -> None:
    controller = InputController()
    page = FakePage()
    browser = browser_with_page(controller, page)
    await browser.apply(Action(1, 0, True), 0)
    browser._on_event(
        None,
        {
            "kind": "command",
            "page_ms": 1,
            "generation": 1,
            "origin": "control",
            "payload": {"command": "toggle_mode"},
        },
    )
    assert not controller.snapshot().owns_ai  # callback has not awaited anything
    assert controller.snapshot().generation == 1
    await browser.close()
    assert page.calls[-1] == "up:Shift"


@async_case
async def test_stale_capture_and_unowned_cleanup_issue_no_input() -> None:
    import time
    from dataclasses import replace

    controller = InputController()
    page = FakePage()
    browser = browser_with_page(controller, page)
    browser._last = replace(snapshot(), captured_at_ns=time.monotonic_ns() - 1_000_000_000)
    assert not (await browser.apply(Action(1, 0, True), 0)).accepted
    await browser.release_owned_inputs()
    assert page.calls == []


@async_case
async def test_revocation_during_pre_dispatch_gate() -> None:
    controller = InputController()

    class RevokingPage(FakePage):
        async def evaluate(self, expression: str, arg: Any = None) -> bool:
            controller.handle(Command.TOGGLE_MODE)
            return True

    page = RevokingPage()
    browser = browser_with_page(controller, page)
    assert not (await browser.apply(Action(1, 0, True), 0)).accepted
    assert page.calls == []
