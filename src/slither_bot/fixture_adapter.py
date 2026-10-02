"""All fixture-specific selectors, state extraction, and start behavior live here."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.async_api import Page

from slither_bot.types import BrowserSnapshot, CanvasBounds, ExtractedGameState, GameStatus


class FixtureAdapter:
    url = (Path(__file__).parent / "fixtures" / "game.html").as_uri()
    boost_key = "Shift"
    boost_code = "ShiftLeft"

    def __init__(self, sectors: int, lifetime_s: float) -> None:
        self.sectors = sectors
        self.lifetime_s = lifetime_s

    async def configure(self, page: Page) -> None:
        await page.evaluate("seconds => window.__fixture.game.lifetime = seconds", self.lifetime_s)

    async def start(self, page: Page) -> None:
        # Fixture lifecycle API avoids synthetic pointer steering during HUMAN mode.
        await page.evaluate("() => window.__fixture.start()")

    async def input_available(self, page: Page, instance_id: int) -> bool:
        result: bool = await page.evaluate(
            """id => window.__fixture?.game.status === 'RUNNING'
                && window.__fixture.game.instance_id === id""",
            instance_id,
        )
        return result

    async def extract(self, page: Page, timestamp: int) -> BrowserSnapshot:
        data: dict[str, Any] | None = await page.evaluate("""() => {
          if (!window.__fixture) return null;
          const r = document.querySelector('#arena').getBoundingClientRect();
          return {game:{...window.__fixture.game}, food:window.__fixture.food,
            rect:{left:r.left, top:r.top, width:r.width, height:r.height},
            viewport:[innerWidth,innerHeight]};
        }""")
        if data is None:
            return BrowserSnapshot(timestamp, GameStatus.UNKNOWN, 0, 0, None)
        g, rect = data["game"], data["rect"]
        canvas = CanvasBounds(**rect)
        # Fixture drawing coordinates are 800x500; pointer and snapshot use viewport CSS pixels.
        x, y = g["x"] * canvas.width / 800, g["y"] * canvas.height / 500
        diagonal = math.hypot(canvas.width, canvas.height)
        boundaries = []
        density = [0.0] * self.sectors
        for i in range(self.sectors):
            dx, dy = math.cos(math.tau * i / self.sectors), math.sin(math.tau * i / self.sectors)
            distances = [diagonal]
            if abs(dx) > 1e-12:
                distances.append(((canvas.width if dx > 0 else 0) - x) / dx)
            if abs(dy) > 1e-12:
                distances.append(((canvas.height if dy > 0 else 0) - y) / dy)
            boundaries.append(max(0.0, min(1.0, min(distances) / diagonal)))
        for food in data["food"]:
            angle = math.atan2(
                food["y"] * canvas.height / 500 - y, food["x"] * canvas.width / 800 - x
            )
            sector = math.floor((angle % math.tau) * self.sectors / math.tau + 0.5) % self.sectors
            density[sector] += 1 / len(data["food"])
        game = ExtractedGameState(
            int(g["instance_id"]),
            canvas,
            (None,) * self.sectors,
            tuple(density),
            tuple(boundaries),
            g["size"],
            g["score"],
            g["heading"],
            g["speed"] * canvas.width / 800,
        )
        return BrowserSnapshot(
            timestamp,
            GameStatus(g["status"]),
            data["viewport"][0],
            data["viewport"][1],
            (canvas.left + x, canvas.top + y),
            game=game,
        )
