"""Streaming JSONL/CSV storage and atomic, truthful checkpoint helpers."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

from slither_bot.types import Action, ActionQuality, ControlMode, Observation, Transition


def json_default(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"Cannot serialize {type(value)}")


def dumps(value: Any) -> str:
    return json.dumps(value, default=json_default, allow_nan=False, separators=(",", ":"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(dumps(value) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def observation_from_dict(data: dict[str, Any]) -> Observation:
    data = dict(data)
    for key in ("enemy_distance", "food_density", "boundary_distance"):
        data[key] = tuple(data[key])
    return Observation(**data)


def transition_from_dict(data: dict[str, Any]) -> Transition:
    data = dict(data)
    data["state"] = observation_from_dict(data["state"])
    if data["next_state"] is not None:
        data["next_state"] = observation_from_dict(data["next_state"])
    data["action"] = Action(**data["action"])
    data["source"] = ControlMode(data["source"])
    data["action_quality"] = ActionQuality(data["action_quality"])
    return Transition(**data)


class RunStorage:
    episode_fields = [
        "episode_id",
        "reward",
        "duration_s",
        "score",
        "maximum_size",
        "ai_steps",
        "human_steps",
        "human_assisted",
        "end_reason",
    ]

    def __init__(self, root: Path, config: Any) -> None:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid4().hex[:8]
        self.path = root / run_id
        (self.path / "transitions").mkdir(parents=True)
        (self.path / "checkpoints").mkdir()
        atomic_json(self.path / "config.json", config)
        self._handles: dict[str, TextIO] = {}
        for name in (
            "events.jsonl",
            "episodes.csv",
            "training.csv",
            "transitions/ai.jsonl",
            "transitions/human.jsonl",
        ):
            self._handles[name] = (self.path / name).open("w", buffering=1)
        self._episodes = csv.DictWriter(self._handles["episodes.csv"], self.episode_fields)
        self._episodes.writeheader()
        self._training = csv.DictWriter(
            self._handles["training.csv"],
            ["step", "status", "loss", "epsilon", "metrics_json"],
        )
        self._training.writeheader()
        self._last_episode = -1

    def event(self, value: Any) -> None:
        self._handles["events.jsonl"].write(dumps(value) + "\n")

    def transition(self, transition: Transition, eligible: bool, reward_terms: Any) -> None:
        name = "ai" if transition.source == ControlMode.AI else "human"
        self._handles[f"transitions/{name}.jsonl"].write(
            dumps(
                {
                    "transition": transition,
                    "replay_eligible": eligible,
                    "reward_terms": reward_terms,
                }
            )
            + "\n"
        )

    def episode(self, values: dict[str, Any]) -> None:
        episode_id = int(values["episode_id"])
        if episode_id <= self._last_episode:
            raise ValueError("Episodes must be finalized exactly once, in order")
        self._episodes.writerow(values)
        self._last_episode = episode_id
        self.flush()

    def training(self, step: int, status: str, metrics: Any = None) -> None:
        metrics = metrics or {}
        self._training.writerow(
            {
                "step": step,
                "status": status,
                "loss": metrics.get("loss"),
                "epsilon": metrics.get("epsilon"),
                "metrics_json": dumps(metrics),
            }
        )

    def flush(self) -> None:
        for handle in self._handles.values():
            handle.flush()

    def close(self) -> None:
        for handle in self._handles.values():
            handle.close()
