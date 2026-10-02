from __future__ import annotations

import asyncio
import csv
import json
import time
from dataclasses import replace
from pathlib import Path

import pytest

from slither_bot.app import Application
from slither_bot.config import Config, RuntimeConfig
from slither_bot.controller import InputController
from slither_bot.model import BaselineAgent
from slither_bot.observer import SnapshotObserver
from slither_bot.replay import BoundedReplay
from slither_bot.reward import LengthReward
from slither_bot.storage import RunStorage, transition_from_dict
from slither_bot.train import ModelWorker, Trainer
from slither_bot.types import (
    ActionQuality,
    Command,
    ControlMode,
    GameStatus,
    InputEvent,
    Observation,
    Prediction,
)
from tests.helpers import FakeBrowser, async_case, snapshot


def make_app(
    tmp_path: Path,
    browser: FakeBrowser,
    config: Config | None = None,
    agent: BaselineAgent | None = None,
) -> Application:
    config = config or Config(runtime=RuntimeConfig(sectors=4, control_hz=1000, max_episodes=2))
    agent = agent or BaselineAgent()
    worker = ModelWorker()
    return Application(
        config,
        browser,
        SnapshotObserver(4),
        InputController(config.runtime.initial_mode),
        agent,
        LengthReward(),
        BoundedReplay(),
        RunStorage(tmp_path, config),
        worker,
        Trainer(agent, worker, config.training),
    )


async def dispose(app: Application) -> None:
    await app.browser.close()
    await app.worker.close()
    app.storage.close()


@async_case
async def test_death_finalized_once_and_auto_restart(tmp_path: Path) -> None:
    browser = FakeBrowser(
        [
            snapshot(GameStatus.MENU, 0),
            snapshot(GameStatus.STARTING, 0),
            snapshot(),
            snapshot(),
            snapshot(GameStatus.DEAD),
            snapshot(GameStatus.DEAD),
            snapshot(GameStatus.STARTING),
            snapshot(instance=2),
            snapshot(instance=2),
            snapshot(GameStatus.DEAD, 2),
        ]
    )
    app = make_app(tmp_path, browser)
    await app.run()
    assert app.completed == 2 and browser.starts == 2 and browser.closed
    with (app.storage.path / "episodes.csv").open() as handle:
        episodes = list(csv.DictReader(handle))
    assert [row["end_reason"] for row in episodes] == ["death", "death"]
    lines = (app.storage.path / "transitions/ai.jsonl").read_text().splitlines()
    transitions = [transition_from_dict(json.loads(line)["transition"]) for line in lines]
    assert sum(t.terminated for t in transitions) == 2
    assert {t.episode_id for t in transitions} == {1, 2}
    assert all(
        t.next_state is None or t.state.episode_id == t.next_state.episode_id for t in transitions
    )
    assert (app.storage.path / "checkpoints/best.json").exists()


@async_case
async def test_mixed_ownership_excluded_and_fresh_return_to_ai(tmp_path: Path) -> None:
    browser = FakeBrowser([snapshot() for _ in range(8)])
    app = make_app(tmp_path, browser)
    await app.tick()
    assert app.pending is not None
    app.controller.handle(Command.TOGGLE_MODE)
    await app.tick()
    assert len(app.replay) == 0 and app.pending is None
    now = time.monotonic_ns()
    browser.events = [
        InputEvent("pointer", now, now, 1, "human_candidate", {"x": 700, "y": 300}),
        InputEvent("boost", now, now, 1, "human_candidate", {"code": "Space", "down": False}),
    ]
    await app.tick()
    assert app.pending is not None and app.pending.source == ControlMode.HUMAN
    await app.tick()
    assert len(browser.applied) == 1 and len(app.replay) == 0
    app.controller.handle(Command.TOGGLE_MODE)
    await app.tick()
    assert app.pending is None and len(browser.applied) == 1
    await app.tick()
    assert app.pending is not None and app.pending.state.sequence == 5
    assert len(browser.applied) == 2
    await dispose(app)
    ai = json.loads((app.storage.path / "transitions/ai.jsonl").read_text().splitlines()[0])
    assert ai["transition"]["action_quality"] == ActionQuality.UNKNOWN
    assert not ai["transition"]["terminated"] and not ai["transition"]["truncated"]
    humans = (app.storage.path / "transitions/human.jsonl").read_text().splitlines()
    assert humans and all(not json.loads(line)["replay_eligible"] for line in humans)


@async_case
async def test_unannounced_respawn_and_requested_restart(tmp_path: Path) -> None:
    browser = FakeBrowser([snapshot(), snapshot(instance=2), snapshot(instance=2)])
    app = make_app(tmp_path, browser)
    await app.tick()
    await app.tick()
    assert app.completed == 1 and app.episode is not None and app.episode.episode_id == 2
    assert len(app.replay) == 0
    app.controller.handle(Command.RESTART)
    await app.tick()
    assert app.completed == 2 and app.episode is None
    await dispose(app)
    rows = [
        json.loads(line)["transition"]
        for line in (app.storage.path / "transitions/ai.jsonl").read_text().splitlines()
    ]
    assert rows[0]["end_reason"] == "respawn" and rows[0]["next_state"] is None
    assert all(row["truncated"] and not row["terminated"] for row in rows)


@async_case
async def test_partial_actions_do_not_become_clean_records(tmp_path: Path) -> None:
    browser = FakeBrowser([snapshot(), snapshot(), snapshot(GameStatus.DEAD)])
    browser.accepted = False
    config = Config(runtime=RuntimeConfig(sectors=4, control_hz=1000, max_episodes=1))
    app = make_app(tmp_path, browser, config)
    await app.run()
    assert len(app.replay) == 0
    assert (app.storage.path / "transitions/ai.jsonl").read_text() == ""


@async_case
async def test_human_death_restarts_but_never_becomes_best(tmp_path: Path) -> None:
    config = Config(runtime=RuntimeConfig(sectors=4, initial_mode=ControlMode.HUMAN))
    browser = FakeBrowser([snapshot(), snapshot(GameStatus.DEAD)])
    app = make_app(tmp_path, browser, config)
    await app.tick()
    await app.tick()
    assert browser.starts == 1 and browser.applied == [] and app.completed == 1
    assert not (app.storage.path / "checkpoints/best.json").exists()
    await dispose(app)


@async_case
async def test_unknown_intervals_do_not_double_count_elapsed_time(tmp_path: Path) -> None:
    base = time.monotonic_ns()
    frames = [replace(snapshot(), captured_at_ns=base)]
    for i in (1, 2):
        frames.append(
            replace(
                snapshot(GameStatus.UNKNOWN), game=None, captured_at_ns=base + i * 1_000_000_000
            )
        )
    frames.append(replace(snapshot(), captured_at_ns=base + 3_000_000_000))
    browser = FakeBrowser(frames)
    app = make_app(tmp_path, browser)
    app.reward = LengthReward(0, 1, 5)
    for _ in range(4):
        await app.tick()
    assert app.episode is not None and app.episode.reward == pytest.approx(3)
    assert len(app.replay) == 0
    await dispose(app)


class SlowAgent(BaselineAgent):
    def predict(self, observation: Observation, *, explore: bool = False) -> Prediction:
        time.sleep(0.03)  # Intentional blocking fake model, isolated in the model worker.
        return super().predict(observation, explore=explore)


@async_case
async def test_hotkey_runs_during_model_work_and_discards_result(tmp_path: Path) -> None:
    browser = FakeBrowser([snapshot()])
    app = make_app(tmp_path, browser, agent=SlowAgent())
    asyncio.get_running_loop().call_later(0.01, app.controller.handle, Command.TOGGLE_MODE)
    await app.tick()
    assert app.controller.snapshot().mode == ControlMode.HUMAN
    assert browser.applied == []
    await dispose(app)


@async_case
async def test_recovery_is_bounded_and_cleanup_runs(tmp_path: Path) -> None:
    config = Config(
        runtime=RuntimeConfig(
            sectors=4, control_hz=500, recovery_timeout_s=0.001, recovery_retries=2
        )
    )
    browser = FakeBrowser([snapshot(GameStatus.UNKNOWN) for _ in range(8)])
    app = make_app(tmp_path, browser, config)
    with pytest.raises(RuntimeError, match="recovery exhausted"):
        await app.run()
    assert browser.starts == 2 and browser.closed


@async_case
async def test_stale_inference_is_not_applied(tmp_path: Path) -> None:
    config = Config(runtime=RuntimeConfig(sectors=4, max_observation_age_s=0.001))
    browser = FakeBrowser([snapshot()])
    app = make_app(tmp_path, browser, config, SlowAgent())
    await app.tick()
    assert not browser.applied and app.pending is None
    await dispose(app)


@async_case
async def test_time_limit_waits_for_new_instance(tmp_path: Path) -> None:
    config = Config(runtime=RuntimeConfig(sectors=4, episode_time_limit_s=0.01))
    first = snapshot()
    expired = replace(first, captured_at_ns=first.captured_at_ns + 20_000_000)
    browser = FakeBrowser([first, expired, expired, snapshot(instance=2)])
    app = make_app(tmp_path, browser, config)
    await app.tick()
    await app.tick()
    assert app.completed == 1 and app.episode is None and browser.starts == 1
    await app.tick()
    assert app.episode is None and app.completed == 1  # old RUNNING instance is retired
    await app.tick()
    assert app.episode is not None and app.episode.instance_id == 2
    await dispose(app)
    row = json.loads((app.storage.path / "transitions/ai.jsonl").read_text().splitlines()[0])
    assert row["transition"]["truncated"] and row["transition"]["end_reason"] == "time_limit"


class SlowStartBrowser(FakeBrowser):
    async def start_episode(self) -> None:
        self.starts += 1
        await asyncio.sleep(1)


@async_case
async def test_start_timeouts_retry_with_a_bound(tmp_path: Path) -> None:
    config = Config(
        runtime=RuntimeConfig(
            sectors=4, control_hz=500, recovery_timeout_s=0.001, recovery_retries=2
        )
    )
    browser = SlowStartBrowser([snapshot(GameStatus.MENU) for _ in range(4)])
    app = make_app(tmp_path, browser, config)
    with pytest.raises(RuntimeError, match="recovery exhausted"):
        await app.run()
    assert browser.starts == 2 and browser.closed


@async_case
async def test_physical_intervention_during_ai_disqualifies_best(tmp_path: Path) -> None:
    browser = FakeBrowser([snapshot(), snapshot(GameStatus.DEAD)])
    app = make_app(tmp_path, browser)
    await app.tick()
    now = time.monotonic_ns()
    browser.events.append(
        InputEvent("boost", now, now, 0, "human_candidate", {"code": "Space", "down": True})
    )
    await app.tick()
    assert app.completed == 1 and len(app.replay) == 0
    assert not (app.storage.path / "checkpoints/best.json").exists()
    await dispose(app)
