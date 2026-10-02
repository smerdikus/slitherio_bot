"""Pure transformation of adapter snapshots into versioned observations."""

from slither_bot.types import BrowserSnapshot, Observation


class SnapshotObserver:
    def __init__(self, sectors: int = 16) -> None:
        if sectors < 1:
            raise ValueError("sectors must be positive")
        self.sectors = sectors

    def observe(self, snapshot: BrowserSnapshot, episode_id: int, sequence: int) -> Observation:
        game = snapshot.game
        if game is None:
            raise ValueError("Snapshot has no extracted state")
        if len(game.enemy_distance) != self.sectors:
            raise ValueError("Adapter sector count does not match observer")
        return Observation(
            episode_id,
            sequence,
            snapshot.captured_at_ns,
            1,
            game.enemy_distance,
            game.food_density,
            game.boundary_distance,
            game.player_size,
            game.score,
            game.heading_rad,
            game.speed,
        )
