from dataclasses import dataclass
from typing import NamedTuple
from decimal import Decimal

@dataclass
class NetworkState:
    power: int
    power_baseline: int
    circulating_supply: Decimal
    epoch_reward: Decimal

    def initial_pledge_for_power(self, power: int) -> Decimal:
        return initial_pledge_for_power(self.power, self.power_baseline, self.epoch_reward, self.circulating_supply,
            power)


INITIAL_PLEDGE_PROJECTION_PERIOD = 20 * 2880
SUPPLY_LOCK_TARGET = Decimal("0.30")


# The initial pledge requirement for an incremental power addition.
def initial_pledge_for_power(network_power: int, network_power_baseline: int, epoch_reward: Decimal,
        circulating_supply: Decimal, power: int) -> Decimal:
    storage = expected_reward_for_power(epoch_reward, network_power, power, INITIAL_PLEDGE_PROJECTION_PERIOD)
    consensus = circulating_supply * Decimal(power) * SUPPLY_LOCK_TARGET / max(network_power, network_power_baseline)
    total = storage + consensus
    return total


# The projected reward that some power would earn over some period.
# TODO: improve to use alpha/beta filter estimates, or something even better.
def expected_reward_for_power(epoch_reward_estimate: Decimal, network_power_estimate: int, power: int,
        duration: int) -> Decimal:
    if network_power_estimate <= 0:
        return epoch_reward_estimate
    return duration * epoch_reward_estimate * power / network_power_estimate
