from dataclasses import dataclass

from consts import DAY

SUPPLY_LOCK_TARGET = 0.30

INITIAL_PLEDGE_PROJECTION_PERIOD = 20 * DAY

@dataclass
class NetworkState:
    epoch: int
    power: int
    power_baseline: int
    circulating_supply: float
    epoch_reward: float

    # The initial pledge requirement for an incremental power addition.
    def initial_pledge_for_power(self, power: int) -> float:
        storage = self.expected_reward_for_power(power, INITIAL_PLEDGE_PROJECTION_PERIOD)
        consensus = self.circulating_supply * power * SUPPLY_LOCK_TARGET / max(self.power, self.power_baseline)
        total = storage + consensus
        return total

    # The projected reward that some power would earn over some period.
    # TODO: improve to use alpha/beta filter estimates, or something even better.
    def expected_reward_for_power(self, power: int, duration: int) -> float:
        if self.power <= 0:
            return self.epoch_reward
        return duration * self.epoch_reward * power / self.power
