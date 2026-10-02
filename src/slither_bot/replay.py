import random
from collections import deque

from slither_bot.types import ActionQuality, ControlMode, Transition


class BoundedReplay:
    """Only clean AI transitions. Human demonstrations have a separate disk stream."""

    def __init__(self, capacity: int = 10_000, seed: int = 0) -> None:
        if capacity < 1:
            raise ValueError("Replay capacity must be positive")
        self._items: deque[Transition] = deque(maxlen=capacity)
        self._rng = random.Random(seed)

    def add(self, transition: Transition) -> bool:
        if transition.source != ControlMode.AI or transition.action_quality != ActionQuality.EXACT:
            return False
        # Truncations need a final state for bootstrapping; terminal death may omit it.
        if transition.next_state is None and not transition.terminated:
            return False
        self._items.append(transition)
        return True

    def sample(self, size: int) -> list[Transition]:
        if size < 1 or size > len(self):
            raise ValueError("Invalid replay sample size")
        return self._rng.sample(list(self._items), size)

    def __len__(self) -> int:
        return len(self._items)
