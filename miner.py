import math
from typing import NamedTuple

from consts import SECTOR_SIZE
from network import NetworkState, MAX_REPAYMENT_REWARD_FRACTION, MAX_REPAYMENT_TERM, MAX_FEE_REWARD_FRACTION

class SectorBunch(NamedTuple):
    power: int
    pledge: float

class MinerState:
    def __init__(self, balance: float):
        self.power: int = 0
        self.balance: float = balance
        self.initial_pledge: float = 0.0
        self.initial_pledge_satisfied: float = 0.0

        self.earned: float = 0.0
        self.burned: float = 0.0

        # Scheduled expiration of power, by epoch.
        self._expirations: dict[int, list[SectorBunch]] = {}

    def summary(self):
        shortfall = self.initial_pledge - self.initial_pledge_satisfied
        shortfall_fraction = 0
        if self.initial_pledge > 0:
            shortfall_fraction = shortfall / self.initial_pledge
        return {
            'power': self.power,
            'balance': self.balance,
            'initial_pledge': self.initial_pledge,
            'initial_pledge_satisfied': self.initial_pledge_satisfied,
            'shortfall': shortfall,
            'shortfall_fraction': shortfall_fraction,
            'available': self.available_balance(),
            'earned': self.earned,
            'burned': self.burned,
        }

    def available_balance(self) -> float:
        return self.balance - self.initial_pledge_satisfied

    def activate_sectors(self, net: NetworkState, power: int, duration: int, pledge: float = float("inf")) -> (int, float):
        """
        Activates power with a specified pledge satisfaction.
        Pledge may be zero for minimum (after shortfall), or inf for the full requirement.
        Returns the power (rounded) and pledge locked.
        """
        # Round the power to a multiple of sector size.
        power = (power // SECTOR_SIZE) * SECTOR_SIZE

        pledge_requirement = net.initial_pledge_for_power(power)
        incremental_shortfall = MAX_REPAYMENT_REWARD_FRACTION * net.expected_reward_for_power(power,
            min(duration, MAX_REPAYMENT_TERM))
        minimum_pledge = pledge_requirement - incremental_shortfall

        if pledge == 0:
            pledge = minimum_pledge
        elif pledge > pledge_requirement:
            pledge = pledge_requirement
        elif pledge < minimum_pledge:
            raise RuntimeError(f"pledge {pledge} less than minimum {pledge_requirement}")
        available = self.available_balance()
        if pledge > available:
            raise RuntimeError(f"insufficient available balance {available} for pledge {pledge}")
        expiration = net.epoch + duration

        self.power += power
        self.initial_pledge += pledge_requirement
        self.initial_pledge_satisfied += pledge
        self._expirations.setdefault(expiration, []).append(SectorBunch(power, pledge_requirement))

        # Sanity check. If this fails, we need to adjust the minimum pledge above to satisfy it.
        # XXX Can we rule out a case where even providing full pledge wouldn't be enough?
        miner_pledge_requirement = net.initial_pledge_for_power(self.power)
        miner_max_shortfall = MAX_REPAYMENT_REWARD_FRACTION * net.expected_reward_for_power(self.power,
            MAX_REPAYMENT_TERM)
        miner_min_satisfaction = miner_pledge_requirement - miner_max_shortfall
        if self.initial_pledge_satisfied < miner_min_satisfaction:
            raise RuntimeError(
                f"miner pledge satisfaction {self.initial_pledge_satisfied} below minimum {miner_min_satisfaction}")

        return power, pledge

    def receive_reward(self, net: NetworkState, reward: float):
        # Vesting is ignored.
        self._earn(reward)

        # Calculate shortfall rate as parameter to repayment and fee.
        assert MAX_FEE_REWARD_FRACTION + MAX_REPAYMENT_REWARD_FRACTION <= 1.0
        shortfall_frac = self.shortfall_fraction(net)

        if shortfall_frac > 0:
            # Burn the fee
            fee_take_rate = shortfall_frac * MAX_FEE_REWARD_FRACTION
            fee_amount = reward * fee_take_rate
            self._burn(fee_amount)

            # Lock repayments as satisified pledge.
            repayment_take_rate = (0.25 + 0.75 * math.sqrt(shortfall_frac)) * MAX_REPAYMENT_REWARD_FRACTION
            repayment_amount = reward * repayment_take_rate
            self.initial_pledge_satisfied += repayment_amount
            assert fee_amount + repayment_amount <= reward

    def handle_epoch(self, net: NetworkState):
        """Executes end-of-epoch state updates"""
        expiring_now = self._expirations.get(net.epoch, [])
        for sb in expiring_now:
            pledge_satisfaction = self.initial_pledge_satisfied / self.initial_pledge
            pledge_to_release = pledge_satisfaction * sb.pledge

            self.power -= sb.power
            self.initial_pledge -= sb.pledge
            self.initial_pledge_satisfied -= pledge_to_release

    def shortfall_fraction(self, net) -> float:
        """The current shortfall as a fraction of the maximum allowed."""
        max_shortfall = MAX_REPAYMENT_REWARD_FRACTION * net.expected_reward_for_power(self.power, MAX_REPAYMENT_TERM)
        actual_shortfall = self.initial_pledge - self.initial_pledge_satisfied
        shortfall_frac = 0.0
        if max_shortfall > 0:
            shortfall_frac = actual_shortfall / max_shortfall
        shortfall_frac = min(shortfall_frac, 1.0)  # Clamp in case of over-shortfall
        return shortfall_frac

    def _earn(self, v: float):
        self.balance += v
        self.earned += v

    def _burn(self, v: float):
        self.balance -= v
        self.burned += v