"""Discrete policy codec and direction-preserving CSS target mapping."""

import math

from slither_bot.types import Action, CanvasBounds

DIRECTIONS = 32
ACTION_COUNT = DIRECTIONS * 2


def decode(action_id: int) -> Action:
    if isinstance(action_id, bool) or not isinstance(action_id, int) or not 0 <= action_id < 64:
        raise ValueError("action_id must be an integer in [0,63]")
    angle = math.tau * (action_id // 2) / DIRECTIONS
    return Action(math.cos(angle), math.sin(angle), bool(action_id % 2))


def encode(action: Action) -> int:
    """Nearest direction; half-sector ties go clockwise. Zero has no direction."""
    if action.dx == 0 and action.dy == 0:
        raise ValueError("Cannot encode a zero direction")
    angle = math.atan2(action.dy, action.dx) % math.tau
    direction = math.floor(angle * DIRECTIONS / math.tau + 0.5) % DIRECTIONS
    return 2 * direction + int(action.boost)


def mouse_target(
    action: Action,
    center: tuple[float, float],
    canvas: CanvasBounds,
    radius: float = 180,
) -> tuple[float, float]:
    """Intersect a ray with an inset canvas rectangle; never clamp axes independently."""
    norm = math.hypot(action.dx, action.dy)
    if norm == 0 or not math.isfinite(norm):
        raise ValueError("Steering requires a finite nonzero direction")
    x, y = center
    left, top = canvas.left + 1, canvas.top + 1
    right, bottom = canvas.left + canvas.width - 1, canvas.top + canvas.height - 1
    if not left < x < right or not top < y < bottom:
        raise ValueError("Player center must be inside the canvas inset")
    dx, dy = action.dx / norm, action.dy / norm
    limits = [radius]
    if dx:
        limits.append(((right if dx > 0 else left) - x) / dx)
    if dy:
        limits.append(((bottom if dy > 0 else top) - y) / dy)
    distance = min(limits)
    return x + dx * distance, y + dy * distance
