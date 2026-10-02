"""Guarded integration with the real Slither client; no fixture fallback."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

from slither_bot.types import BrowserSnapshot, CanvasBounds, ExtractedGameState, GameStatus

if TYPE_CHECKING:
    from playwright.async_api import Page


class SlitherAdapter:
    url = "http://slither.com/io"
    boost_key = "Space"
    boost_code = "Space"

    def __init__(self, sectors: int, nickname: str = "slither-bot") -> None:
        self.sectors = sectors
        self.nickname = nickname
        self._previous: tuple[int, int, float, float] | None = None

    async def configure(self, page: Page) -> None:
        await page.wait_for_function(
            "('slither' in window || 'snake' in window) && typeof window.connect === 'function'"
        )
        await page.evaluate((Path(__file__).parent / "scripts/slither_adapter.js").read_text())

    async def start(self, page: Page) -> None:
        await page.evaluate("name => window.__slitherAdapter.start(name)", self.nickname)
        self._previous = None

    async def input_available(self, page: Page, instance_id: int) -> bool:
        available: bool = await page.evaluate(
            "id => window.__slitherAdapter?.available(id) === true", instance_id
        )
        return available

    async def extract(self, page: Page, timestamp: int) -> BrowserSnapshot:
        data: dict[str, Any] | None = await page.evaluate(
            "n => window.__slitherAdapter?.capture(n) ?? null", self.sectors
        )
        if data is None:
            return BrowserSnapshot(timestamp, GameStatus.UNKNOWN, 0, 0, None)
        game = None
        speed = None
        instance = int(data["instance_id"])
        if data["world"] is not None and data["scale"] is not None:
            x, y = data["world"]
            sx, sy = data["scale"]
            previous = self._previous
            if previous is not None and previous[0] == instance and timestamp > previous[1]:
                speed = math.hypot((x - previous[2]) * sx, (y - previous[3]) * sy) / (
                    (timestamp - previous[1]) / 1e9
                )
            self._previous = (instance, timestamp, x, y)
        else:
            self._previous = None
        if data["rect"] is not None:
            game = ExtractedGameState(
                instance,
                CanvasBounds(**data["rect"]),
                tuple(data["enemies"]),
                tuple(data["food"]),
                tuple(data["boundary"]),
                data["size"],
                data["score"],
                data["heading"],
                speed,
            )
        return BrowserSnapshot(
            timestamp,
            GameStatus(data["status"]),
            data["viewport"][0],
            data["viewport"][1],
            tuple(data["center"]) if data["center"] is not None else None,
            game=game,
        )
