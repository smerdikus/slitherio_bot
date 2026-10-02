from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any

from slither_bot.types import (
    Action,
    ActionReceipt,
    BrowserSnapshot,
    CanvasBounds,
    ExtractedGameState,
    GameStatus,
    InputEvent,
    Observation,
)


def async_case[**P](function: Callable[P, Coroutine[Any, Any, None]]) -> Callable[P, None]:
    """Each scenario owns an event loop, like the CLI; no async fixture lifecycle coupling."""

    @wraps(function)
    def run(*args: P.args, **kwargs: P.kwargs) -> None:
        asyncio.run(function(*args, **kwargs))

    return run


def observation(sequence: int = 0, episode_id: int = 1, size: float | None = 10) -> Observation:
    return Observation(
        episode_id,
        sequence,
        1_000_000_000 + sequence * 100_000_000,
        1,
        (None,) * 4,
        (0.0,) * 4,
        (0.5,) * 4,
        player_size=size,
    )


def snapshot(status: GameStatus = GameStatus.RUNNING, instance: int = 1) -> BrowserSnapshot:
    return BrowserSnapshot(
        time.monotonic_ns(),
        status,
        1000,
        800,
        (450.0, 350.0),
        game=ExtractedGameState(
            instance,
            CanvasBounds(50, 100, 800, 500),
            (None,) * 4,
            (0.0,) * 4,
            (0.5,) * 4,
            10,
            1,
            0,
            60,
        ),
    )


class FakeBrowser:
    def __init__(self, snapshots: list[BrowserSnapshot]) -> None:
        self.snapshots = snapshots
        self.applied: list[tuple[Action, int]] = []
        self.events: list[InputEvent] = []
        self.starts = 0
        self.releases = 0
        self.closed = False
        self.accepted = True

    async def launch(self) -> None:
        pass

    async def capture(self) -> BrowserSnapshot:
        return self.snapshots.pop(0)

    async def start_episode(self) -> None:
        self.starts += 1

    async def apply(self, action: Action, generation: int) -> ActionReceipt:
        self.applied.append((action, generation))
        now = time.monotonic_ns()
        return ActionReceipt(generation, now, now, True, self.accepted, self.accepted)

    async def release_owned_inputs(self) -> None:
        self.releases += 1

    def drain_events(self) -> list[InputEvent]:
        events, self.events = self.events, []
        return events

    async def close(self) -> None:
        await self.release_owned_inputs()
        self.closed = True
