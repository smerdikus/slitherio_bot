from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from slither_bot.config import Config
from slither_bot.main import build
from slither_bot.slither_adapter import SlitherAdapter
from slither_bot.types import GameStatus
from tests.helpers import async_case

if TYPE_CHECKING:
    from playwright.async_api import Page


class StatePage:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {
            "status": "RUNNING",
            "instance_id": 1,
            "viewport": [900, 600],
            "center": [420, 280],
            "rect": {"left": 20, "top": 30, "width": 800, "height": 500},
            "world": [500, 500],
            "scale": [1, 1],
            "size": 10,
            "score": 10,
            "heading": 0,
            "enemies": [0.1, 1, 1, 1],
            "food": [1, 0, 0, 0],
            "boundary": [1, 1, 1, 1],
        }

    async def evaluate(self, script: str, arg: Any = None) -> dict[str, Any]:
        return self.data


@async_case
async def test_live_snapshot_projection_speed_and_respawn() -> None:
    adapter = SlitherAdapter(4)
    fake = StatePage()
    page = cast("Page", fake)
    first = await adapter.extract(page, 1_000_000_000)
    assert first.status == GameStatus.RUNNING and first.player_center == (420, 280)
    assert first.game is not None and first.game.speed is None
    fake.data["world"] = [520, 500]
    second = await adapter.extract(page, 2_000_000_000)
    assert second.game is not None and second.game.speed == pytest.approx(20)
    fake.data["instance_id"] = 2
    third = await adapter.extract(page, 3_000_000_000)
    assert third.game is not None and third.game.speed is None
    fake.data.update(world=None, scale=None, center=None, size=None, score=None, status="DEAD")
    dead = await adapter.extract(page, 4_000_000_000)
    assert dead.status == GameStatus.DEAD and dead.player_center is None
    assert dead.game is not None and dead.game.player_size is None


@async_case
async def test_default_application_uses_real_website(tmp_path: Path) -> None:
    app = build(Config(runs_dir=tmp_path))
    from slither_bot.browser import PlaywrightGameBrowser

    assert isinstance(app.browser, PlaywrightGameBrowser)
    assert isinstance(app.browser.adapter, SlitherAdapter)
    assert app.browser.adapter.url == "http://slither.com/io"
    await app.worker.close()
    app.storage.close()
