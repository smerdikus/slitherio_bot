import asyncio
import time
from dataclasses import replace

from slither_bot.config import TrainingConfig
from slither_bot.model import BaselineAgent
from slither_bot.replay import BoundedReplay
from slither_bot.train import ModelWorker, Trainer
from tests.helpers import async_case
from tests.test_core import transition


@async_case
async def test_training_permission_and_unsupported_are_truthful() -> None:
    worker = ModelWorker()
    trainer = Trainer(
        BaselineAgent(),
        worker,
        replace(TrainingConfig(), warmup_steps=1, batch_size=1, every_steps=1),
    )
    replay = BoundedReplay()
    replay.add(transition())
    try:
        assert await trainer.maybe_train(replay, 1, False) is None
        assert not trainer.unsupported
        assert await trainer.maybe_train(replay, 1, True) is None
        assert trainer.unsupported
    finally:
        await worker.close()


@async_case
async def test_model_operations_are_serialized() -> None:
    worker = ModelWorker()
    calls: list[str] = []

    def job(label: str) -> str:
        calls.append(label + "-start")
        time.sleep(0.01)
        calls.append(label + "-end")
        return label

    try:
        result = await asyncio.gather(worker.call(job, "predict"), worker.call(job, "save"))
        assert list(result) == ["predict", "save"]
        assert calls == ["predict-start", "predict-end", "save-start", "save-end"]
    finally:
        await worker.close()
