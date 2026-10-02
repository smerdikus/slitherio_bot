"""The small game-specific boundary within the browser layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from slither_bot.types import BrowserSnapshot

if TYPE_CHECKING:
    from playwright.async_api import Page


class GameAdapter(Protocol):
    url: str
    boost_key: str
    boost_code: str

    async def configure(self, page: Page) -> None: ...
    async def start(self, page: Page) -> None: ...
    async def input_available(self, page: Page, instance_id: int) -> bool: ...
    async def extract(self, page: Page, timestamp: int) -> BrowserSnapshot: ...
