from dataclasses import dataclass

from consts import DAY, SECTOR_SIZE

SUPPLY_LOCK_TARGET = 0.30

INITIAL_PLEDGE_PROJECTION_PERIOD = 20 * DAY

MAX_REPAYMENT_TERM = 365 * DAY
MAX_REPAYMENT_REWARD_FRACTION = 0.75
MAX_FEE_REWARD_FRACTION = 0.25

@dataclass
class NetworkState:
    epoch: int
    power: int
    power_baseline: int
    circulating_supply: float
    epoch_reward: float

    def initial_pledge_for_power(self, power: int) -> float:
        """The initial pledge requirement for an incremental power addition."""
        storage = self.expected_reward_for_power(power, INITIAL_PLEDGE_PROJECTION_PERIOD)
        consensus = self.circulating_supply * power * SUPPLY_LOCK_TARGET / max(self.power, self.power_baseline)
        return storage + consensus

    def power_for_initial_pledge(self, pledge: float) -> int:
        """The maximum power that can be committed for an incremental pledge."""
        # TODO: this is coupled with the simplified expected_reward_for_power
        power = pledge * self.power / \
                (INITIAL_PLEDGE_PROJECTION_PERIOD * self.epoch_reward + self.circulating_supply * SUPPLY_LOCK_TARGET)
        return int((power // SECTOR_SIZE) * SECTOR_SIZE)

    def expected_reward_for_power(self, power: int, duration: int) -> float:
        """The projected reward that some power would earn over some period."""
        # TODO: improve to use alpha/beta filter estimates, or something even better.
        if self.power <= 0:
            return self.epoch_reward
        return duration * self.epoch_reward * power / self.power

    def max_pledge_for_tokens(self, satisfaction: float) -> float:
        """The maximum incremental initial pledge allowed for an incremental satisfaction."""
        # TODO: this is coupled with the simplified expected_reward_for_power
        # TODO: add duration parameter = min (duration, MAX_REPAYMENT_TERM)
        return satisfaction / (1 - MAX_REPAYMENT_REWARD_FRACTION * MAX_REPAYMENT_TERM * self.epoch_reward / (
                    INITIAL_PLEDGE_PROJECTION_PERIOD * self.epoch_reward + SUPPLY_LOCK_TARGET * self.circulating_supply))
