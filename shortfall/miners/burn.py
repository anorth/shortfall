from typing import Callable

from ..consts import SECTOR_SIZE
from ..miners.base import BaseMinerState, SectorBunch
from ..network import NetworkState


class BurnShortfallMinerState(BaseMinerState):
    """A miner that burns an equivalent amount to the shortfall, but never pledges it."""

    # The maximum shortfall as a fraction of nominal pledge requirement.
    DEFAULT_MAX_SHORTFALL_FRACTION = 0.33  # Likely in the range 25-50%.
    # Exponent of the current shortfall fraction determining the take rate from rewards.
    DEFAULT_SHORTFALL_TAKE_RATE_EXPONENT = 0.75

    @staticmethod
    def factory(balance: float,
            max_shortfall_fraction: float = DEFAULT_MAX_SHORTFALL_FRACTION,
            shortfall_take_rate_exponent: float = DEFAULT_SHORTFALL_TAKE_RATE_EXPONENT,
    ) -> Callable[[], BaseMinerState]:
        """Returns a function that creates new miner states."""
        return lambda: BurnShortfallMinerState(balance=balance,
            max_shortfall_fraction=max_shortfall_fraction,
            shortfall_take_rate_exponent=shortfall_take_rate_exponent)

    def __init__(self, balance: float,
            max_shortfall_fraction: float = DEFAULT_MAX_SHORTFALL_FRACTION,
            shortfall_take_rate_exponent: float = DEFAULT_SHORTFALL_TAKE_RATE_EXPONENT):
        super().__init__(balance)
        self.max_shortfall_fraction = max_shortfall_fraction
        self.shortfall_take_rate_exponent = shortfall_take_rate_exponent
        # Amount of burn obligation not yet paid.
        self.fee_pending: float = 0

    def summary(self, rounding=4):
        summary = super().summary(rounding)
        summary.update({
            'fee_pending': round(self.fee_pending, rounding),
        })
        return summary

    # Override
    def max_pledge_for_tokens(self, net: NetworkState, available_lock: float,
            duration: int) -> float:
        """The maximum incremental initial pledge commitment allowed for an incremental locking."""
        return available_lock / (1 - self.max_shortfall_fraction)

    # Overrides
    def activate_sectors(self, net: NetworkState, power: int, duration: int,
            lock: float = float("inf")) -> (
            int, float):
        """
        Activates power and locks a specified pledge.
        Lock may be 0, meaning to lock the minimum (after shortfall), or inf to lock the full pledge requirement.
        If available balance is insufficient for the specified locking, the tokens are leased.
        Returns the power and pledge locked.
        """
        assert power % SECTOR_SIZE == 0

        pledge_requirement = net.initial_pledge_for_power(power)
        minimum_pledge = pledge_requirement * (1 - self.max_shortfall_fraction)

        if lock == 0:
            lock = minimum_pledge
        elif lock > pledge_requirement:
            lock = pledge_requirement
        elif lock < minimum_pledge:
            raise RuntimeError(f"lock {lock} is less than minimum pledge {pledge_requirement}")
        self._lease(max(lock - self.available_balance(), 0))

        self.power += power
        # Only the initially locked amount is ever required to be pledged.
        self.pledge_locked += lock
        # Captures the shortfall from the notional initial pledge.
        self.fee_pending += pledge_requirement - lock

        expiration = net.epoch + duration
        self._expirations.setdefault(expiration, []).append(SectorBunch(power, lock))

        return power, lock

    # Override
    def receive_reward(self, net: NetworkState, reward: float):
        # Vesting is ignored.
        self._earn_reward(reward)

        # Calculate and burn shortfall fee
        if self.fee_pending > 0:
            # Approximate original pledge requirement as true pledge plus outstanding shortfall.
            # This starts off correct, but then underestimates as the shortfall is paid off,
            # resulting in a higher payoff rate than if the original pledge intention were
            # accounted explicitly.
            collateral_target = self.pledge_locked + self.fee_pending
            shortfall_fraction = self.fee_pending / collateral_target

            BASE_BURN_RATE = 0.01
            fee_take_rate = min(
                BASE_BURN_RATE + shortfall_fraction ** self.shortfall_take_rate_exponent, 1.0)
            assert fee_take_rate >= 0
            assert fee_take_rate <= 1.0
            if fee_take_rate > 0:
                # Burn the fee
                fee_amount = min(reward * fee_take_rate, self.fee_pending)
                self._burn_fee(fee_amount)
                self.fee_pending -= fee_amount

        # Repay lease if possible.
        self._repay(min(self.lease, self.available_balance()))

    def handle_expiration(self, sectors: SectorBunch):
        # Reduce (forgive) the outstanding fee in proportion to the power represented.
        # XXX it's not clear that this is appropriate policy.
        remaining_power_frac = (self.power - sectors.power) / self.power
        self.fee_pending *= remaining_power_frac

        self.power -= sectors.power
        self.pledge_locked -= sectors.pledge
