import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from slither_bot.actions import decode, encode, mouse_target
from slither_bot.config import Config
from slither_bot.human import HumanInput
from slither_bot.model import BaselineAgent
from slither_bot.replay import BoundedReplay
from slither_bot.reward import LengthReward
from slither_bot.storage import RunStorage, dumps, transition_from_dict
from slither_bot.types import (
    Action,
    ActionQuality,
    CanvasBounds,
    ControlMode,
    InputEvent,
    Transition,
)
from tests.helpers import observation


@pytest.mark.parametrize("action_id", range(64))
def test_codec_round_trip(action_id: int) -> None:
    action = decode(action_id)
    assert encode(action) == action_id
    assert action.boost == bool(action_id % 2)
    assert math.hypot(action.dx, action.dy) == pytest.approx(1)


@pytest.mark.parametrize("bad", [-1, 64, True, 1.5, "1"])
def test_codec_rejects_invalid_ids(bad: object) -> None:
    with pytest.raises(ValueError):
        decode(bad)  # type: ignore[arg-type]


def test_codec_zero_nonfinite_and_nearest() -> None:
    with pytest.raises(ValueError):
        encode(Action(0, 0))
    with pytest.raises(ValueError):
        Action(math.nan, 0)
    assert encode(Action(100, 1, True)) == 1
    assert encode(Action(0, -100)) == 48


def test_target_preserves_direction_near_edge_with_css_offset() -> None:
    x, y = mouse_target(Action(3, 4), (840, 580), CanvasBounds(50, 100, 800, 500))
    assert 50 < x < 850 and 100 < y < 600
    assert (y - 580) / (x - 840) == pytest.approx(4 / 3)
    with pytest.raises(ValueError):
        mouse_target(Action(1, 1), (0, 0), CanvasBounds(50, 100, 800, 500))


def test_observation_missing_and_validation() -> None:
    obs = observation()
    assert obs.enemy_distance[0] is None and obs.food_density[0] == 0
    for changes in (
        {"food_density": (0.0,)},
        {"speed": math.inf},
        {"boundary_distance": (0.0, 0.0, math.nan, 0.0)},
    ):
        with pytest.raises(ValueError):
            replace(obs, **changes)


def test_reward_uses_duration_and_missing_measurement() -> None:
    reward = LengthReward(2, 0.5, 10)
    result = reward.calculate(observation(size=10), observation(1, size=12), Action(1, 0), 2, True)
    assert (result.growth, result.survival, result.death, result.total) == (4, 1, -10, -5)
    assert not result.missing_size
    result = reward.calculate(
        observation(size=None), observation(1, size=12), Action(1, 0), 2, False
    )
    assert result.missing_size and result.growth == 0 and result.total == 1
    assert reward.calculate(observation(), None, Action(1, 0), 1, True).missing_size


def transition(step: int = 0) -> Transition:
    return Transition(
        1,
        step,
        observation(step),
        Action(1, 0),
        1,
        observation(step + 1),
        False,
        False,
        ControlMode.AI,
        0.1,
    )


def test_replay_capacity_sampling_and_eligibility() -> None:
    a, b = BoundedReplay(3, 123), BoundedReplay(3, 123)
    for i in range(5):
        assert a.add(transition(i)) and b.add(transition(i))
    assert len(a) == 3
    assert a.sample(3) == b.sample(3)
    assert {t.step_id for t in a.sample(3)} == {2, 3, 4}
    assert not a.add(replace(transition(), source=ControlMode.HUMAN))
    assert not a.add(replace(transition(), action_quality=ActionQuality.UNKNOWN))
    assert not a.add(replace(transition(), next_state=None))
    assert not a.add(replace(transition(), truncated=True, next_state=None))
    assert a.add(replace(transition(), terminated=True, next_state=None))
    with pytest.raises(ValueError):
        a.sample(4)
    with pytest.raises(ValueError):
        replace(transition(), next_state=observation(1, episode_id=2))


def test_storage_round_trip_and_atomic_checkpoint(tmp_path: Path) -> None:
    original = transition()
    assert transition_from_dict(json.loads(dumps(original))) == original
    terminal = replace(original, next_state=None, terminated=True, end_reason="death")
    assert transition_from_dict(json.loads(dumps(terminal))) == terminal
    storage = RunStorage(tmp_path, Config())
    storage.transition(original, True, {"missing_size": False})
    storage.event(InputEvent("pointer", 1, 2, 0, "human_candidate", {"x": 12}))
    values: dict[str, object] = dict.fromkeys(storage.episode_fields)
    values["episode_id"] = 1
    storage.episode(values)
    with pytest.raises(ValueError):
        storage.episode(values)
    storage.close()
    row = json.loads((storage.path / "transitions/ai.jsonl").read_text())
    assert transition_from_dict(row["transition"]) == original
    agent = BaselineAgent("random", 123)
    path = storage.path / "checkpoints/latest.json"
    agent.save(path)
    expected = agent.predict(observation())
    agent.load(path)
    assert agent.predict(observation()) == expected
    assert not list(path.parent.glob("*.pt"))
    assert list(path.parent.iterdir()) == [path]
    with pytest.raises(ValueError):
        agent.save(path.with_suffix(".pt"))
    with pytest.raises(NotImplementedError):
        agent.train_step([original])


def test_human_state_unknown_until_pointer_and_boost_known() -> None:
    human = HumanInput()
    assert human.action((100, 100)) is None
    human.ingest(InputEvent("pointer", 1, 1, 1, "human_candidate", {"x": 130, "y": 140}))
    assert human.action((100, 100)) is None
    human.ingest(InputEvent("boost", 2, 2, 1, "human_candidate", {"code": "Space", "down": False}))
    assert human.action((100, 100)) == Action(0.6, 0.8, False)
    human.ingest(InputEvent("command", 3, 3, 2, "control", {"command": "toggle_mode"}))
    assert human.action((100, 100)) is None
