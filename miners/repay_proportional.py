import math
from typing import Callable

from consts import DAY, SECTOR_SIZE
from miners.base import BaseMinerState, SectorBunch
from network import NetworkState, INITIAL_PLEDGE_PROJECTION_PERIOD, SUPPLY_LOCK_TARGET

class RepayProportionalShortfallMinerState(BaseMinerState):
    """
    A miner that repays a shortfall, as well as paying a fee.
    The fraction of rewards taken for repayment depends on the current shortfall amount.
    """

    MAX_REPAYMENT_TERM = 365 * DAY
    MAX_REPAYMENT_REWARD_FRACTION = 0.75
    MAX_FEE_REWARD_FRACTION = 0.25
    MIN_REPAYMENT_TAKE_FRACTION = 0.25

    @staticmethod
    def factory(balance: float) -> Callable[[], BaseMinerState]:
        """Returns a function that creates new miner states."""
        return lambda: RepayProportionalShortfallMinerState(balance=balance)

    def __init__(self, balance: float):
        super().__init__(balance)
        self.pledge_required: float = 0

    def summary(self, rounding=4):
        shortfall = self.pledge_required - self.pledge_locked
        shortfall_pct = 0
        if self.pledge_required > 0:
            shortfall_pct = round(100 * shortfall / self.pledge_required, 2)
        summary = super().summary(rounding)
        summary.update({
            'pledge_required': round(self.pledge_required, rounding),
            'shortfall': round(shortfall, rounding),
            'shortfall_pct': shortfall_pct,
        })
        return summary

    # Override
    def max_pledge_for_tokens(self, net: NetworkState, available_lock: float) -> float:
        """The maximum incremental initial pledge commitment allowed for an incremental locking."""
        # TODO: add duration parameter = min (duration, MAX_REPAYMENT_TERM)
        return available_lock / (1 - self.MAX_REPAYMENT_REWARD_FRACTION * net.projected_reward(net.epoch_reward, self.MAX_REPAYMENT_TERM) / (
                 net.projected_reward(net.epoch_reward, INITIAL_PLEDGE_PROJECTION_PERIOD) + SUPPLY_LOCK_TARGET * net.circulating_supply))

    # Override
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
        incremental_shortfall = self.MAX_REPAYMENT_REWARD_FRACTION * net.expected_reward_for_power(power,
            min(duration, self.MAX_REPAYMENT_TERM))
        minimum_pledge = pledge_requirement - incremental_shortfall

        if lock == 0:
            lock = minimum_pledge
        elif lock > pledge_requirement:
            lock = pledge_requirement
        elif lock < minimum_pledge:
            raise RuntimeError(f"lock {lock} is less than minimum pledge {minimum_pledge}")
        self._lease(max(lock - self.available_balance(), 0))

        self.power += power
        self.pledge_required += pledge_requirement
        self.pledge_locked += lock

        expiration = net.epoch + duration
        self._expirations.setdefault(expiration, []).append(SectorBunch(power, pledge_requirement))

        # Sanity check. If this fails, we need to adjust the minimum pledge above to satisfy it.
        # XXX Can we rule out a case where even providing full pledge wouldn't be enough?
        miner_pledge_requirement = net.initial_pledge_for_power(self.power)
        miner_max_shortfall = self.MAX_REPAYMENT_REWARD_FRACTION * net.expected_reward_for_power(self.power,
            self.MAX_REPAYMENT_TERM)
        miner_min_satisfaction = miner_pledge_requirement - miner_max_shortfall
        if self.pledge_locked < miner_min_satisfaction:
            raise RuntimeError(
                f"miner pledge satisfaction {self.pledge_locked} below minimum {miner_min_satisfaction}")

        return power, lock

    # Override
    def receive_reward(self, net: NetworkState, reward: float):
        # Vesting is ignored.
        self._earn_reward(reward)

        # Calculate shortfall rate as parameter to repayment and fee.
        assert self.MAX_FEE_REWARD_FRACTION + self.MAX_REPAYMENT_REWARD_FRACTION <= 1.0
        shortfall_frac = self.shortfall_fraction(net)

        if shortfall_frac > 0:
            # Burn the fee
            fee_take_rate = shortfall_frac * self.MAX_FEE_REWARD_FRACTION
            fee_amount = reward * fee_take_rate
            self._burn_fee(fee_amount)

            # Lock repayments as satisified pledge.
            repayment_take_rate = (self.MIN_REPAYMENT_TAKE_FRACTION +
                                   (1 - self.MIN_REPAYMENT_TAKE_FRACTION) * math.sqrt(
                        shortfall_frac)) * self.MAX_REPAYMENT_REWARD_FRACTION
            repayment_amount = reward * repayment_take_rate
            self.pledge_locked += repayment_amount
            assert fee_amount + repayment_amount <= reward

        # Repay lease if possible.
        self._repay(min(self.lease, self.available_balance()))

    # Override
    def handle_expiration(self, sectors: SectorBunch):
        pledge_satisfaction = self.pledge_locked / self.pledge_required
        pledge_to_release = pledge_satisfaction * sectors.pledge

        self.power -= sectors.power
        self.pledge_required -= sectors.pledge
        self.pledge_locked -= pledge_to_release

    def shortfall_fraction(self, net: NetworkState) -> float:
        """The current shortfall as a fraction of the maximum allowed."""
        max_shortfall = self.MAX_REPAYMENT_REWARD_FRACTION * net.expected_reward_for_power(self.power,
            self.MAX_REPAYMENT_TERM)
        actual_shortfall = self.pledge_required - self.pledge_locked
        shortfall_frac = 0.0
        if max_shortfall > 0:
            shortfall_frac = actual_shortfall / max_shortfall
        shortfall_frac = min(shortfall_frac, 1.0)  # Clamp in case of over-shortfall
        return shortfall_frac
