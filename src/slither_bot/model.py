"""Agents know observations/actions only. Importing this module never imports torch."""

import json
import math
import random
from collections.abc import Mapping, Sequence
from pathlib import Path

from slither_bot.actions import decode, encode
from slither_bot.storage import atomic_json
from slither_bot.types import Action, Observation, Prediction, Transition


class BaselineAgent:
    policy_version = "baseline-v1"

    def __init__(self, kind: str = "deterministic", seed: int = 0) -> None:
        if kind not in {"deterministic", "random"}:
            raise ValueError("Unsupported baseline")
        self.kind = kind
        self._rng = random.Random(seed)

    def predict(self, observation: Observation, *, explore: bool = False) -> Prediction:
        if self.kind == "random":
            action_id = self._rng.randrange(64)
        else:
            distances = observation.boundary_distance
            known = [(i, d) for i, d in enumerate(distances) if d is not None]
            sector = max(known, key=lambda pair: pair[1])[0] if known else 0
            angle = math.tau * sector / len(distances)
            action_id = encode(
                Action(math.cos(angle), math.sin(angle), observation.sequence % 50 < 5)
            )
        return Prediction(decode(action_id), action_id, f"{self.policy_version}-{self.kind}")

    def train_step(self, batch: Sequence[Transition]) -> Mapping[str, float]:
        raise NotImplementedError("BaselineAgent cannot train; implement a learning Agent first")

    def save(self, path: Path) -> None:
        if path.suffix != ".json":
            raise ValueError("Baseline checkpoints use .json; .pt is reserved for PyTorch")
        atomic_json(
            path,
            {
                "format": "slither-baseline-v1",
                "kind": self.kind,
                "rng_state": self._rng.getstate(),
            },
        )

    def load(self, path: Path) -> None:
        state = json.loads(path.read_text())
        if state["format"] != "slither-baseline-v1":
            raise ValueError("Unsupported baseline checkpoint")
        if state["kind"] not in {"deterministic", "random"}:
            raise ValueError("Invalid checkpoint agent kind")
        self.kind = state["kind"]
        version, internal, gaussian = state["rng_state"]
        self._rng.setstate((version, tuple(internal), gaussian))
