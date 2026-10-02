from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from slither_bot.types import ControlMode


@dataclass(frozen=True)
class BrowserConfig:
    headless: bool = False
    width: int = 1100
    height: int = 800
    screenshots: bool = False
    timeout_s: float = 5.0
    fixture_lifetime_s: float = 12.0


@dataclass(frozen=True)
class RuntimeConfig:
    control_hz: float = 10.0
    sectors: int = 16
    max_observation_age_s: float = 0.3
    episode_time_limit_s: float = 60.0
    recovery_timeout_s: float = 5.0
    recovery_retries: int = 3
    max_episodes: int = 0
    run_seconds: float = 0.0
    initial_mode: ControlMode = ControlMode.AI


@dataclass(frozen=True)
class TrainingConfig:
    replay_capacity: int = 10_000
    batch_size: int = 64
    warmup_steps: int = 256
    every_steps: int = 10


@dataclass(frozen=True)
class RewardConfig:
    length_gain_weight: float = 1.0
    survival_reward_per_second: float = 0.1
    death_penalty: float = 5.0


@dataclass(frozen=True)
class KeyBindings:
    toggle_mode: str = "F8"
    toggle_training: str = "F9"
    checkpoint: str = "F10"
    restart: str = "F11"
    shutdown: str = "Escape"


@dataclass(frozen=True)
class Config:
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)
    reward: RewardConfig = field(default_factory=RewardConfig)
    keys: KeyBindings = field(default_factory=KeyBindings)
    runs_dir: Path = Path("runs")
    seed: int = 0
    agent: str = "deterministic"

    def __post_init__(self) -> None:
        positive = (
            self.runtime.control_hz,
            self.runtime.max_observation_age_s,
            self.runtime.episode_time_limit_s,
            self.runtime.recovery_timeout_s,
            self.browser.timeout_s,
            self.browser.fixture_lifetime_s,
        )
        if any(not math.isfinite(v) or v <= 0 for v in positive):
            raise ValueError("Timing values must be finite and positive")
        if (
            min(
                self.browser.width,
                self.browser.height,
                self.runtime.sectors,
                self.runtime.recovery_retries,
                self.training.replay_capacity,
                self.training.batch_size,
                self.training.every_steps,
            )
            < 1
        ):
            raise ValueError("Dimensions, counts, and capacities must be positive")
        if (
            self.runtime.max_episodes < 0
            or self.runtime.run_seconds < 0
            or not math.isfinite(self.runtime.run_seconds)
            or self.training.warmup_steps < 0
        ):
            raise ValueError("Limits must be nonnegative and finite")
        if self.agent not in {"deterministic", "random"}:
            raise ValueError("Unknown baseline agent")
        keys = vars(self.keys).values()
        if len(set(keys)) != len(vars(self.keys)) or any(not k for k in keys):
            raise ValueError("Shortcut codes must be unique and nonempty")
        if any(k in {"Space", "ShiftLeft", "ShiftRight"} for k in keys):
            raise ValueError("Shortcut codes cannot overlap boost keys")
        if any(not math.isfinite(v) for v in vars(self.reward).values()):
            raise ValueError("Reward weights must be finite")

    @classmethod
    def load(cls, path: Path) -> Config:
        data: dict[str, Any] = json.loads(path.read_text())
        constructors = {
            "browser": BrowserConfig,
            "runtime": RuntimeConfig,
            "training": TrainingConfig,
            "reward": RewardConfig,
            "keys": KeyBindings,
        }
        for key, constructor in constructors.items():
            if key in data:
                values = data[key]
                if key == "runtime" and "initial_mode" in values:
                    values["initial_mode"] = ControlMode(values["initial_mode"])
                data[key] = constructor(**values)
        if "runs_dir" in data:
            data["runs_dir"] = Path(data["runs_dir"])
        return cls(**data)
