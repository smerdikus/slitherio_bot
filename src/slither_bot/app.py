"""Episode lifecycle, interval attribution, recording, and model coordination."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, replace

from slither_bot.actions import encode
from slither_bot.config import Config
from slither_bot.human import HumanInput
from slither_bot.storage import RunStorage
from slither_bot.train import ModelWorker, Trainer
from slither_bot.types import (
    Action,
    ActionQuality,
    Agent,
    BrowserSnapshot,
    Controller,
    ControlMode,
    GameBrowser,
    GameStatus,
    Observation,
    Observer,
    ReplayBuffer,
    RewardFunction,
    Transition,
)

log = logging.getLogger(__name__)


@dataclass
class Episode:
    episode_id: int
    instance_id: int
    first: Observation
    last: Observation
    reward: float = 0.0
    maximum_size: float | None = None
    ai_steps: int = 0
    human_steps: int = 0
    human_assisted: bool = False
    step_id: int = 0
    accounted_at_ns: int = 0
    measurement_gap: bool = False


@dataclass
class Pending:
    state: Observation
    action: Action
    generation: int
    source: ControlMode
    action_id: int | None
    policy_version: str | None
    quality: ActionQuality
    human_revision: int
    dirty: bool = False


class Application:
    def __init__(
        self,
        config: Config,
        browser: GameBrowser,
        observer: Observer,
        controller: Controller,
        agent: Agent,
        reward: RewardFunction,
        replay: ReplayBuffer,
        storage: RunStorage,
        worker: ModelWorker,
        trainer: Trainer,
    ) -> None:
        self.config = config
        self.browser = browser
        self.observer = observer
        self.controller = controller
        self.agent = agent
        self.reward = reward
        self.replay = replay
        self.storage = storage
        self.worker = worker
        self.trainer = trainer
        self.human = HumanInput()
        self.episode: Episode | None = None
        self.pending: Pending | None = None
        self.completed = 0
        self.total_steps = 0
        self._episode_id = 0
        self._restart_seen = 0
        self._checkpoint_seen = 0
        self._generation = controller.snapshot().generation
        self._recovery_since: float | None = None
        self._recovery_attempts = 0
        self._start_requested = False
        self._best_reward = float("-inf")
        self._retired_instance: int | None = None

    def _drain_events(self) -> None:
        for event in self.browser.drain_events():
            self.storage.event(event)
            self.human.ingest(event)
            pending = self.pending
            if self.episode is not None and (
                (event.kind == "command" and event.payload.get("command") == "toggle_mode")
                or (event.kind == "focus" and not event.payload.get("focused"))
                or (event.kind in {"pointer", "boost"} and event.origin == "human_candidate")
            ):
                self.episode.human_assisted = True
            if pending is not None and event.captured_at_ns >= pending.state.captured_at_ns:
                if event.generation != pending.generation:
                    pending.dirty = True
                if event.kind in {"pointer", "boost"} and event.origin == "human_candidate":
                    pending.dirty = True

    def _observation(self, snapshot: BrowserSnapshot) -> Observation | None:
        episode = self.episode
        if (
            episode is None
            or snapshot.game is None
            or snapshot.game.instance_id != episode.instance_id
        ):
            return None
        try:
            return self.observer.observe(snapshot, episode.episode_id, episode.last.sequence + 1)
        except ValueError as exc:
            self.storage.event({"kind": "invalid_observation", "message": str(exc)})
            return None

    def _settle(
        self,
        current: Observation | None,
        *,
        terminated: bool = False,
        truncated: bool = False,
        reason: str | None = None,
        now_ns: int | None = None,
    ) -> None:
        episode, pending = self.episode, self.pending
        self.pending = None
        if episode is None:
            return
        previous = (
            replace(episode.last, player_size=None) if episode.measurement_gap else episode.last
        )
        end_ns = current.captured_at_ns if current is not None else (now_ns or time.monotonic_ns())
        duration = max(0.0, (end_ns - episode.accounted_at_ns) / 1e9)
        episode.accounted_at_ns = end_ns
        episode.measurement_gap = current is None
        terms = self.reward.calculate(
            previous,
            current,
            pending.action if pending else Action(0, 0),
            duration,
            terminated,
        )
        episode.reward += terms.total
        self.storage.event(
            {
                "kind": "reward",
                "episode_id": episode.episode_id,
                "captured_at_ns": end_ns,
                "terms": terms,
            }
        )
        if pending is not None:
            state = self.controller.snapshot()
            mixed = pending.generation != state.generation or pending.source != state.mode
            quality = pending.quality
            if (
                mixed
                or pending.dirty
                or (
                    pending.source == ControlMode.HUMAN
                    and pending.human_revision != self.human.revision
                )
            ):
                quality = ActionQuality.UNKNOWN
            transition = Transition(
                episode.episode_id,
                episode.step_id,
                pending.state,
                pending.action,
                terms.total,
                current,
                terminated,
                truncated,
                pending.source,
                duration,
                pending.action_id,
                pending.policy_version,
                quality,
                reason,
            )
            eligible = self.replay.add(transition)
            self.storage.transition(transition, eligible, terms)
            episode.step_id += 1
            self.total_steps += 1
            if pending.source == ControlMode.AI:
                episode.ai_steps += 1
            else:
                episode.human_steps += 1
        if current is not None:
            episode.last = current
            if current.player_size is not None:
                episode.maximum_size = max(
                    episode.maximum_size or current.player_size, current.player_size
                )

    async def _finalize(self, reason: str, now_ns: int) -> None:
        episode, self.episode = self.episode, None
        self.pending = None
        if episode is None:
            return
        self._retired_instance = episode.instance_id
        self.storage.episode(
            {
                "episode_id": episode.episode_id,
                "reward": episode.reward,
                "duration_s": max(0.0, (now_ns - episode.first.captured_at_ns) / 1e9),
                "score": episode.last.score,
                "maximum_size": episode.maximum_size,
                "ai_steps": episode.ai_steps,
                "human_steps": episode.human_steps,
                "human_assisted": episode.human_assisted,
                "end_reason": reason,
            }
        )
        self.completed += 1
        log.info("Episode %s ended: %s, reward %.3f", episode.episode_id, reason, episode.reward)
        # Only completed, AI-only death episodes qualify for this simple evaluation convention.
        if (
            reason == "death"
            and not episode.human_assisted
            and episode.ai_steps > 0
            and episode.reward > self._best_reward
        ):
            self._best_reward = episode.reward
            await self.worker.call(self.agent.save, self.storage.path / "checkpoints" / "best.json")
        await self.browser.release_owned_inputs()
        self.human.reset()
        self._start_requested = False
        self._recovery_since = None

    async def _recover(self, snapshot: BrowserSnapshot) -> None:
        now = time.monotonic()
        if self._recovery_since is None:
            self._recovery_since = now
        elapsed = now - self._recovery_since
        if not self._start_requested or elapsed >= self.config.runtime.recovery_timeout_s:
            if self._recovery_attempts >= self.config.runtime.recovery_retries:
                raise RuntimeError(f"Game recovery exhausted in {snapshot.status}")
            self._recovery_attempts += 1
            self._recovery_since = now
            self._start_requested = True
            try:
                await asyncio.wait_for(
                    self.browser.start_episode(),
                    timeout=self.config.runtime.recovery_timeout_s,
                )
            except TimeoutError:
                self._start_requested = False
                self.storage.event({"kind": "start_timeout", "attempt": self._recovery_attempts})

    async def tick(self) -> None:
        snapshot = await asyncio.wait_for(
            self.browser.capture(),
            timeout=self.config.browser.timeout_s,
        )
        self._drain_events()
        control = self.controller.snapshot()
        changed_generation = control.generation != self._generation
        if changed_generation:
            self._generation = control.generation
            await self.browser.release_owned_inputs()
            # Clear inferred human state at every ownership boundary; never assume held keys.
            # Page events since the boundary may have already re-established that state.
        if self.episode is not None and (control.mode == ControlMode.HUMAN or changed_generation):
            self.episode.human_assisted = True
        if control.checkpoint_requests > self._checkpoint_seen:
            self._checkpoint_seen = control.checkpoint_requests
            await self.worker.call(
                self.agent.save, self.storage.path / "checkpoints" / "latest.json"
            )
        restart = control.restart_requests > self._restart_seen
        self._restart_seen = control.restart_requests
        episode = self.episode
        observation = self._observation(snapshot)
        respawn = (
            episode is not None
            and snapshot.game is not None
            and (snapshot.game.instance_id != episode.instance_id)
        )
        timed_out = (
            episode is not None
            and (snapshot.captured_at_ns - episode.first.captured_at_ns) / 1e9
            >= self.config.runtime.episode_time_limit_s
        )
        if episode is not None:
            if snapshot.status == GameStatus.DEAD and not respawn:
                self._settle(
                    observation, terminated=True, reason="death", now_ns=snapshot.captured_at_ns
                )
                await self._finalize("death", snapshot.captured_at_ns)
            elif restart or timed_out or respawn or control.shutdown:
                reason = (
                    "shutdown"
                    if control.shutdown
                    else "restart"
                    if restart
                    else "respawn"
                    if respawn
                    else "time_limit"
                )
                self._settle(
                    None if respawn else observation,
                    truncated=True,
                    reason=reason,
                    now_ns=snapshot.captured_at_ns,
                )
                await self._finalize(reason, snapshot.captured_at_ns)
            elif (
                snapshot.status != GameStatus.RUNNING
                or observation is None
                or snapshot.player_center is None
            ):
                # Drop uncertain intervals; recovery cannot create cross-gap transitions.
                if self.pending is not None:
                    self.pending.dirty = True
                self._settle(None, now_ns=snapshot.captured_at_ns)
                await self.browser.release_owned_inputs()
                if self._recovery_since is None:
                    self._recovery_since = time.monotonic()
                if (
                    time.monotonic() - self._recovery_since
                    >= self.config.runtime.recovery_timeout_s
                ):
                    await self._finalize("status_timeout", snapshot.captured_at_ns)
                return
            else:
                self._settle(observation)
        if control.shutdown or (
            self.config.runtime.max_episodes and self.completed >= self.config.runtime.max_episodes
        ):
            return
        if restart or timed_out:
            await self._recover(snapshot)
            return
        if self.episode is None:
            if (
                snapshot.status == GameStatus.RUNNING
                and snapshot.game is not None
                and snapshot.player_center is not None
                and snapshot.game.instance_id != self._retired_instance
                and not restart
            ):
                # Never begin again from the same terminal snapshot.
                self._episode_id += 1
                try:
                    observation = self.observer.observe(snapshot, self._episode_id, 0)
                except ValueError:
                    await self._recover(snapshot)
                    return
                self.episode = Episode(
                    self._episode_id,
                    snapshot.game.instance_id,
                    observation,
                    observation,
                    maximum_size=observation.player_size,
                    human_assisted=control.mode == ControlMode.HUMAN,
                    accounted_at_ns=observation.captured_at_ns,
                )
                self.human.reset()
            else:
                await self._recover(snapshot)
                return
        self._recovery_attempts = 0
        self._recovery_since = None
        self._start_requested = False
        if observation is None or snapshot.player_center is None:
            await self.browser.release_owned_inputs()
            return
        if changed_generation and control.owns_ai:
            # The capture above may predate a toggle delivered during capture/checkpoint I/O.
            # Wait for the next tick and its fresh observation before predicting.
            return
        await self._act(snapshot, observation)
        was_unsupported = self.trainer.unsupported
        metrics = await self.trainer.maybe_train(
            self.replay,
            self.total_steps,
            self.controller.snapshot().training_enabled,
        )
        if metrics is not None:
            self.storage.training(self.total_steps, "trained", metrics)
        elif self.trainer.unsupported and not was_unsupported:
            self.storage.training(self.total_steps, "unsupported")

    async def _act(self, snapshot: BrowserSnapshot, observation: Observation) -> None:
        control = self.controller.snapshot()
        if control.generation != self._generation:
            return
        if control.owns_ai:
            input_revision = self.human.revision
            prediction = await self.worker.call(self.agent.predict, observation, explore=False)
            # Input callbacks still run while model work is in its serialized worker.
            self._drain_events()
            if self.controller.snapshot().generation != control.generation:
                return
            if (time.monotonic_ns() - observation.captured_at_ns) / 1e9 > (
                self.config.runtime.max_observation_age_s
            ):
                self.storage.event({"kind": "stale_prediction", "sequence": observation.sequence})
                await self.browser.release_owned_inputs()
                return
            receipt = await asyncio.wait_for(
                self.browser.apply(prediction.action, control.generation),
                timeout=self.config.browser.timeout_s,
            )
            if receipt.accepted:
                self.pending = Pending(
                    observation,
                    prediction.action,
                    control.generation,
                    ControlMode.AI,
                    prediction.action_id,
                    prediction.policy_version,
                    ActionQuality.EXACT,
                    self.human.revision,
                    dirty=self.human.revision != input_revision,
                )
        elif control.mode == ControlMode.HUMAN and control.focused:
            action = self.human.action(snapshot.player_center)
            if action is not None:
                self.pending = Pending(
                    observation,
                    action,
                    control.generation,
                    ControlMode.HUMAN,
                    encode(action),
                    None,
                    ActionQuality.QUANTIZED,
                    self.human.revision,
                )

    async def run(self) -> None:
        started = time.monotonic()
        reason = "shutdown"
        try:
            await self.browser.launch()
            log.info("Recording to %s", self.storage.path)
            while not self.controller.snapshot().shutdown:
                tick_started = time.monotonic()
                await self.tick()
                if (
                    self.config.runtime.max_episodes
                    and self.completed >= self.config.runtime.max_episodes
                ):
                    break
                if (
                    self.config.runtime.run_seconds
                    and time.monotonic() - started >= self.config.runtime.run_seconds
                ):
                    reason = "run_time_limit"
                    break
                # Schedule from this tick, not accumulated deadlines: no catch-up bursts.
                await asyncio.sleep(
                    max(0.0, 1 / self.config.runtime.control_hz - (time.monotonic() - tick_started))
                )
        except BaseException:
            reason = "exception"
            raise
        finally:
            try:
                self._drain_events()
                if self.episode is not None:
                    self._settle(None, truncated=True, reason=reason)
                    await self._finalize(reason, time.monotonic_ns())
            finally:
                try:
                    await self.browser.close()
                finally:
                    self._drain_events()
                    try:
                        await self.worker.close()
                    finally:
                        self.storage.close()
