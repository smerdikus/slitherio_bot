"""Conservative sampled human steering. Raw input remains authoritative."""

import math

from slither_bot.types import Action, InputEvent


class HumanInput:
    def __init__(self) -> None:
        self.pointer: tuple[float, float] | None = None
        self.boost: bool | None = None
        self.revision = 0
        self._other_boost: set[str] = set()

    def reset(self) -> None:
        self.pointer = None
        self.boost = None
        self.revision += 1

    def ingest(self, event: InputEvent) -> None:
        if event.kind == "command" and event.payload.get("command") in {
            "toggle_mode",
            "restart",
            "shutdown",
        }:
            self.reset()
        elif event.kind == "focus":
            self.reset()
        elif event.origin == "human_candidate":
            if event.kind == "pointer":
                pointer = (float(event.payload["x"]), float(event.payload["y"]))
                if pointer != self.pointer:
                    self.pointer = pointer
                    self.revision += 1
            elif event.kind == "boost" and event.payload.get("code") == "Space":
                boost = bool(event.payload["down"])
                if self.boost != boost:
                    self.boost = boost
                    self.revision += 1
            elif event.kind == "boost":
                # Space is the supported demonstration boost control. Other game controls
                # remain in raw events and invalidate labels rather than guessing their OR state.
                self.boost = None
                code = str(event.payload.get("code", "unknown"))
                if event.payload.get("down"):
                    self._other_boost.add(code)
                else:
                    self._other_boost.discard(code)
                self.revision += 1
        elif event.origin == "automation_candidate" and event.kind in {"pointer", "boost"}:
            # Could be a coincident physical event; never use it as a human label.
            self.revision += 1

    def action(self, center: tuple[float, float] | None) -> Action | None:
        if self.pointer is None or self.boost is None or center is None or self._other_boost:
            return None
        dx, dy = self.pointer[0] - center[0], self.pointer[1] - center[1]
        norm = math.hypot(dx, dy)
        if norm < 1e-9:
            return None
        return Action(dx / norm, dy / norm, self.boost)
