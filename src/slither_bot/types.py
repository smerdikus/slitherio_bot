"""Standard-library-only shared contracts.

Sectors run clockwise in screen axes, starting at right (angle zero). Sector i
is centered on 2*pi*i/N. Distances divide by canvas diagonal and clamp to [0,1].
Food density is a [0,1] occupancy fraction. None means unavailable, never zero.
Size/score use adapter-defined game units; heading is radians; speed is CSS px/s.
All timestamps are host monotonic nanoseconds, not wall-clock dates.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol


class ControlMode(StrEnum):
    AI = "AI"
    HUMAN = "HUMAN"


class GameStatus(StrEnum):
    MENU = "MENU"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEAD = "DEAD"
    UNKNOWN = "UNKNOWN"


class ActionQuality(StrEnum):
    EXACT = "exact"
    QUANTIZED = "quantized"
    UNKNOWN = "unknown"


class Command(StrEnum):
    TOGGLE_MODE = "toggle_mode"
    TOGGLE_TRAINING = "toggle_training"
    CHECKPOINT = "checkpoint"
    RESTART = "restart"
    SHUTDOWN = "shutdown"
    FOCUS_LOST = "focus_lost"


@dataclass(frozen=True)
class Action:
    dx: float
    dy: float
    boost: bool = False

    def __post_init__(self) -> None:
        if not all(math.isfinite(v) for v in (self.dx, self.dy)):
            raise ValueError("Action direction must be finite")
        if not isinstance(self.boost, bool):
            raise ValueError("boost must be a bool")


@dataclass(frozen=True)
class Observation:
    episode_id: int
    sequence: int
    captured_at_ns: int
    schema_version: int
    enemy_distance: tuple[float | None, ...]
    food_density: tuple[float | None, ...]
    boundary_distance: tuple[float | None, ...]
    player_size: float | None = None
    score: float | None = None
    heading_rad: float | None = None
    speed: float | None = None

    def __post_init__(self) -> None:
        if self.episode_id < 0 or self.sequence < 0 or self.captured_at_ns < 0:
            raise ValueError("Negative observation identifier/timestamp")
        if self.schema_version != 1:
            raise ValueError("Unsupported observation schema")
        n = len(self.enemy_distance)
        if not n or len(self.food_density) != n or len(self.boundary_distance) != n:
            raise ValueError("Feature lengths must be equal and nonempty")
        for values in (self.enemy_distance, self.food_density, self.boundary_distance):
            if any(v is not None and (not math.isfinite(v) or not 0 <= v <= 1) for v in values):
                raise ValueError("Known sector features must be finite and normalized to [0,1]")
        for value in (self.player_size, self.score, self.heading_rad, self.speed):
            if value is not None and not math.isfinite(value):
                raise ValueError("Known scalar features must be finite")


@dataclass(frozen=True)
class CanvasBounds:
    left: float
    top: float
    width: float
    height: float


@dataclass(frozen=True)
class ExtractedGameState:
    """Typed adapter output; instance_id must change at every respawn."""

    instance_id: int
    canvas: CanvasBounds
    enemy_distance: tuple[float | None, ...]
    food_density: tuple[float | None, ...]
    boundary_distance: tuple[float | None, ...]
    player_size: float | None
    score: float | None
    heading_rad: float | None
    speed: float | None


@dataclass(frozen=True)
class BrowserSnapshot:
    captured_at_ns: int
    status: GameStatus
    viewport_width: int
    viewport_height: int
    player_center: tuple[float, float] | None
    screenshot: bytes | None = None
    game: ExtractedGameState | None = None


@dataclass(frozen=True)
class Prediction:
    action: Action
    action_id: int | None
    policy_version: str
    log_prob: float | None = None
    value: float | None = None


@dataclass(frozen=True)
class ActionReceipt:
    generation: int
    started_at_ns: int
    finished_at_ns: int
    steering_applied: bool = False
    boost_applied: bool = False
    accepted: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class InputEvent:
    kind: str
    captured_at_ns: int
    received_at_ns: int
    generation: int
    origin: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    clock_uncertainty_ns: int = 0


@dataclass(frozen=True)
class ControlState:
    mode: ControlMode = ControlMode.AI
    generation: int = 0
    focused: bool = True
    training_enabled: bool = False
    checkpoint_requests: int = 0
    restart_requests: int = 0
    shutdown: bool = False

    @property
    def owns_ai(self) -> bool:
        return self.mode == ControlMode.AI and self.focused and not self.shutdown


@dataclass(frozen=True)
class RewardResult:
    total: float
    growth: float
    survival: float
    death: float
    missing_size: bool


@dataclass(frozen=True)
class Transition:
    episode_id: int
    step_id: int
    state: Observation
    action: Action
    reward: float
    next_state: Observation | None
    terminated: bool
    truncated: bool
    source: ControlMode
    duration_s: float
    action_id: int | None = None
    policy_version: str | None = None
    action_quality: ActionQuality = ActionQuality.EXACT
    end_reason: str | None = None

    def __post_init__(self) -> None:
        if self.state.episode_id != self.episode_id:
            raise ValueError("State episode mismatch")
        if self.next_state is not None:
            if self.next_state.episode_id != self.episode_id:
                raise ValueError("Cross-episode transitions are forbidden")
            if self.next_state.sequence <= self.state.sequence:
                raise ValueError("Next state must be newer")
            if self.next_state.captured_at_ns < self.state.captured_at_ns:
                raise ValueError("Next state timestamp precedes state")
        if self.terminated and self.truncated:
            raise ValueError("Transition cannot terminate and truncate together")
        if not math.isfinite(self.reward) or not math.isfinite(self.duration_s):
            raise ValueError("Reward and duration must be finite")
        if self.duration_s < 0:
            raise ValueError("Negative duration")

    @property
    def done(self) -> bool:
        return self.terminated or self.truncated


class GameBrowser(Protocol):
    async def launch(self) -> None: ...
    async def capture(self) -> BrowserSnapshot: ...
    async def start_episode(self) -> None: ...
    async def apply(self, action: Action, generation: int) -> ActionReceipt: ...
    async def release_owned_inputs(self) -> None: ...
    def drain_events(self) -> list[InputEvent]: ...
    async def close(self) -> None: ...


class Observer(Protocol):
    def observe(self, snapshot: BrowserSnapshot, episode_id: int, sequence: int) -> Observation: ...


class Agent(Protocol):
    def predict(self, observation: Observation, *, explore: bool = False) -> Prediction: ...
    def train_step(self, batch: Sequence[Transition]) -> Mapping[str, float]: ...
    def save(self, path: Path) -> None: ...
    def load(self, path: Path) -> None: ...


class Controller(Protocol):
    def snapshot(self) -> ControlState: ...
    def handle(self, command: Command) -> None: ...


class RewardFunction(Protocol):
    def calculate(
        self,
        previous: Observation,
        current: Observation | None,
        action: Action,
        duration_s: float,
        terminated: bool,
    ) -> RewardResult: ...


class ReplayBuffer(Protocol):
    def add(self, transition: Transition) -> bool: ...
    def sample(self, size: int) -> list[Transition]: ...
    def __len__(self) -> int: ...
