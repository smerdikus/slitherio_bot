from dataclasses import dataclass

from slither_bot.types import Action, Observation, RewardResult


@dataclass(frozen=True)
class LengthReward:
    length_gain_weight: float = 1.0
    survival_reward_per_second: float = 0.1
    death_penalty: float = 5.0

    def calculate(
        self,
        previous: Observation,
        current: Observation | None,
        action: Action,
        duration_s: float,
        terminated: bool,
    ) -> RewardResult:
        missing = previous.player_size is None or current is None or current.player_size is None
        growth = 0.0
        if (
            current is not None
            and current.player_size is not None
            and previous.player_size is not None
        ):
            growth = self.length_gain_weight * (current.player_size - previous.player_size)
        survival = self.survival_reward_per_second * duration_s
        death = -self.death_penalty * int(terminated)
        return RewardResult(growth + survival + death, growth, survival, death, missing)
