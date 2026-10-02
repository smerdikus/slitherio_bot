"""Serialized model work and honest scheduling; no browser automation."""

import asyncio
import logging
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import TypeVar

from slither_bot.config import TrainingConfig
from slither_bot.types import Agent, ReplayBuffer

T = TypeVar("T")
log = logging.getLogger(__name__)


class ModelWorker:
    """One thread for prediction, training, and checkpoints; no overlapping model access.

    Future PyTorch code belongs here. Cancelling an await does not stop a running
    native operation; stale generations are rejected by the runtime/browser.
    """

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="slither-model")

    async def call(self, function: Callable[..., T], *args: object, **kwargs: object) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, partial(function, *args, **kwargs))

    async def close(self) -> None:
        await asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=True)


class Trainer:
    def __init__(self, agent: Agent, worker: ModelWorker, config: TrainingConfig) -> None:
        self.agent = agent
        self.worker = worker
        self.config = config
        self.unsupported = False
        self._last_step = -1

    async def maybe_train(
        self,
        replay: ReplayBuffer,
        step: int,
        enabled: bool,
    ) -> Mapping[str, float] | None:
        if not enabled or self.unsupported or step == self._last_step:
            return None
        if len(replay) < max(self.config.warmup_steps, self.config.batch_size):
            return None
        if step % self.config.every_steps:
            return None
        self._last_step = step
        try:
            return await self.worker.call(
                self.agent.train_step, replay.sample(self.config.batch_size)
            )
        except NotImplementedError as exc:
            self.unsupported = True
            log.warning("Training permission is on, but training is unsupported: %s", exc)
            return None
