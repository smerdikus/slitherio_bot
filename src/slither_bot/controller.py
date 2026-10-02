"""Synchronous, event-loop-owned command/ownership state."""

from dataclasses import replace

from slither_bot.types import Command, ControlMode, ControlState


class InputController:
    def __init__(self, mode: ControlMode = ControlMode.AI) -> None:
        self._state = ControlState(mode=mode)

    def snapshot(self) -> ControlState:
        return self._state

    def handle(self, command: Command) -> None:
        state = self._state
        match command:
            case Command.TOGGLE_MODE:
                mode = ControlMode.HUMAN if state.mode == ControlMode.AI else ControlMode.AI
                self._state = replace(state, mode=mode, generation=state.generation + 1)
            case Command.FOCUS_LOST:
                self._state = replace(
                    state,
                    mode=ControlMode.HUMAN,
                    focused=False,
                    generation=state.generation + 1,
                )
            case Command.RESTART:
                self._state = replace(
                    state,
                    generation=state.generation + 1,
                    restart_requests=state.restart_requests + 1,
                )
            case Command.SHUTDOWN:
                self._state = replace(state, shutdown=True, generation=state.generation + 1)
            case Command.TOGGLE_TRAINING:
                self._state = replace(state, training_enabled=not state.training_enabled)
            case Command.CHECKPOINT:
                self._state = replace(state, checkpoint_requests=state.checkpoint_requests + 1)

    def focus_gained(self) -> None:
        # Refocus never restores AI. A subsequent explicit toggle is required.
        self._state = replace(self._state, focused=True)
