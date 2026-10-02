"""Opt-in automation smoke test. This does NOT verify a physical mouse takeover."""

import asyncio
import os
from dataclasses import replace

import pytest

from slither_bot.browser import PlaywrightGameBrowser
from slither_bot.config import Config, RuntimeConfig
from slither_bot.controller import InputController
from slither_bot.fixture_adapter import FixtureAdapter
from slither_bot.types import Action, ControlMode, GameStatus
from tests.helpers import async_case

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_BROWSER_TESTS") != "1",
        reason="Set RUN_BROWSER_TESTS=1 to launch Chromium",
    ),
]


@async_case
async def test_fixture_steering_boost_takeover_death_and_restart() -> None:
    config = Config(runtime=RuntimeConfig(sectors=8))
    config = replace(config, browser=replace(config.browser, headless=True, fixture_lifetime_s=0.7))
    controller = InputController()
    browser = PlaywrightGameBrowser(config, controller, FixtureAdapter(8, 0.7))
    try:
        await browser.launch()
        assert (await browser.capture()).status == GameStatus.MENU
        await browser.start_episode()
        page = browser.page
        assert page is not None
        await page.wait_for_function("window.__fixture.game.status === 'RUNNING'")
        before = await browser.capture()
        assert before.game is not None
        assert (await browser.apply(Action(0, 1, True), 0)).accepted
        assert await page.evaluate("window.__fixture.boost.ai") is True
        await page.keyboard.down("Space")
        await page.keyboard.press("F8")
        await asyncio.sleep(0.05)
        assert controller.snapshot().mode == ControlMode.HUMAN
        assert await page.evaluate("window.__fixture.boost.ai") is False
        assert await page.evaluate("window.__fixture.boost.human") is True
        assert not (await browser.apply(Action(1, 0), 0)).accepted
        await page.mouse.move(600, 300)
        await page.keyboard.up("Space")
        await page.wait_for_function("window.__fixture.game.status === 'DEAD'")
        dead = await browser.capture()
        assert dead.game is not None and dead.game.player_size is not None
        assert (
            before.game.player_size is not None and dead.game.player_size > before.game.player_size
        )
        events = browser.drain_events()
        assert any(e.kind == "automation_command" for e in events)
        assert any(e.kind == "pointer" and e.origin == "human_candidate" for e in events)
        await browser.start_episode()
        await page.wait_for_function("window.__fixture.game.status === 'RUNNING'")
        restarted = await browser.capture()
        assert restarted.game is not None and restarted.game.instance_id != dead.game.instance_id
    finally:
        await browser.close()
