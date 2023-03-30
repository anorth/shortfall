import math
from dataclasses import dataclass
from typing import NamedTuple

from consts import SECTOR_SIZE
from network import NetworkState, MAX_REPAYMENT_REWARD_FRACTION, MAX_REPAYMENT_TERM, MAX_FEE_REWARD_FRACTION

@dataclass
class MinerConfig:
    balance: float

class SectorBunch(NamedTuple):
    power: int
    pledge: float

class MinerState:
    def __init__(self, cfg: MinerConfig):
        self.power: int = 0
        self.balance: float = cfg.balance
        self.lease: float = 0.0
        self.pledge_required: float = 0.0
        self.pledge_locked: float = 0.0

        self.reward_earned: float = 0.0
        self.shortfall_fee_burned: float = 0.0
        self.lease_fee_accrued = 0.0

        # Scheduled expiration of power, by epoch.
        self._expirations: dict[int, list[SectorBunch]] = {}

    def summary(self, rounding=4):
        shortfall = self.pledge_required - self.pledge_locked
        shortfall_pct = 0
        if self.pledge_required > 0:
            shortfall_pct = round(100 * shortfall / self.pledge_required, 2)
        net_equity = self.balance - self.lease
        return {
            'power': self.power,
            'balance': round(self.balance, rounding),
            'lease': round(self.lease, rounding),
            'pledge_required': round(self.pledge_required, rounding),
            'pledge_locked': round(self.pledge_locked, rounding),
            'shortfall': round(shortfall, rounding),
            'shortfall_pct': shortfall_pct,
            'available': round(self.available_balance(), rounding),
            'net_equity': round(net_equity, rounding),

            'reward_earned': round(self.reward_earned, rounding),
            'shortfall_fee_burned': round(self.shortfall_fee_burned, rounding),
            'lease_fee_accrued': round(self.lease_fee_accrued, rounding),
        }

    def available_balance(self) -> float:
        return self.balance - self.pledge_locked

    def activate_sectors(self, net: NetworkState, power: int, duration: int, lock: float = float("inf")) -> (
    int, float):
        """
        Activates power and locks a specified pledge.
        Lock may be 0, meaning to lock the minimum (after shortfall), or inf to lock the full pledge requirement.
        If available balance is insufficient for the specified locking, the tokens are leased.
        Returns the power and pledge locked.
        """
        assert power % SECTOR_SIZE == 0

        pledge_requirement = net.initial_pledge_for_power(power)
        incremental_shortfall = MAX_REPAYMENT_REWARD_FRACTION * net.expected_reward_for_power(power,
            min(duration, MAX_REPAYMENT_TERM))
        minimum_pledge = pledge_requirement - incremental_shortfall

        if lock == 0:
            lock = minimum_pledge
        elif lock > pledge_requirement:
            lock = pledge_requirement
        elif lock < minimum_pledge:
            raise RuntimeError(f"lock {lock} is less than minimum pledge {pledge_requirement}")
        self._lease(max(lock - self.available_balance(), 0))

        self.power += power
        self.pledge_required += pledge_requirement
        self.pledge_locked += lock
        expiration = net.epoch + duration
        self._expirations.setdefault(expiration, []).append(SectorBunch(power, pledge_requirement))

        # Sanity check. If this fails, we need to adjust the minimum pledge above to satisfy it.
        # XXX Can we rule out a case where even providing full pledge wouldn't be enough?
        miner_pledge_requirement = net.initial_pledge_for_power(self.power)
        miner_max_shortfall = MAX_REPAYMENT_REWARD_FRACTION * net.expected_reward_for_power(self.power,
            MAX_REPAYMENT_TERM)
        miner_min_satisfaction = miner_pledge_requirement - miner_max_shortfall
        if self.pledge_locked < miner_min_satisfaction:
            raise RuntimeError(
                f"miner pledge satisfaction {self.pledge_locked} below minimum {miner_min_satisfaction}")

        return power, lock

    def receive_reward(self, net: NetworkState, reward: float):
        # Vesting is ignored.
        self._earn_reward(reward)

        # Calculate shortfall rate as parameter to repayment and fee.
        assert MAX_FEE_REWARD_FRACTION + MAX_REPAYMENT_REWARD_FRACTION <= 1.0
        shortfall_frac = self.shortfall_fraction(net)

        if shortfall_frac > 0:
            # Burn the fee
            fee_take_rate = shortfall_frac * MAX_FEE_REWARD_FRACTION
            fee_amount = reward * fee_take_rate
            self._burn_fee(fee_amount)

            # Lock repayments as satisified pledge.
            repayment_take_rate = (0.25 + 0.75 * math.sqrt(shortfall_frac)) * MAX_REPAYMENT_REWARD_FRACTION
            repayment_amount = reward * repayment_take_rate
            self.pledge_locked += repayment_amount
            assert fee_amount + repayment_amount <= reward

        # Repay lease if possible.
        self._repay(min(self.lease, self.available_balance()))

    def handle_epoch(self, net: NetworkState):
        """Executes end-of-epoch state updates"""
        # Accrue token lease fees.
        # The fee is added to the repayment obligation. If the miner has funds, it will pay it next epoch.
        fee = net.fee_for_token_lease(self.lease, 1)
        self._accrue_lease_fee(fee)

        # Expire power.
        expiring_now = self._expirations.get(net.epoch, [])
        for sb in expiring_now:
            pledge_satisfaction = self.pledge_locked / self.pledge_required
            pledge_to_release = pledge_satisfaction * sb.pledge

            self.power -= sb.power
            self.pledge_required -= sb.pledge
            self.pledge_locked -= pledge_to_release

    def shortfall_fraction(self, net) -> float:
        """The current shortfall as a fraction of the maximum allowed."""
        max_shortfall = MAX_REPAYMENT_REWARD_FRACTION * net.expected_reward_for_power(self.power, MAX_REPAYMENT_TERM)
        actual_shortfall = self.pledge_required - self.pledge_locked
        shortfall_frac = 0.0
        if max_shortfall > 0:
            shortfall_frac = actual_shortfall / max_shortfall
        shortfall_frac = min(shortfall_frac, 1.0)  # Clamp in case of over-shortfall
        return shortfall_frac

    def _earn_reward(self, v: float):
        assert v >= 0
        self.balance += v
        self.reward_earned += v

    def _burn_fee(self, v: float):
        assert v >= 0
        assert v <= self.available_balance()
        self.balance -= v
        self.shortfall_fee_burned += v

    def _lease(self, v: float):
        assert v >= 0
        self.balance += v
        self.lease += v

    def _repay(self, v: float):
        assert v >= 0
        assert v <= self.lease
        assert v <= self.available_balance()
        self.balance -= v
        self.lease -= v

    def _accrue_lease_fee(self, v: float):
        assert v >= 0
        self.lease += v
        self.lease_fee_accrued += v
