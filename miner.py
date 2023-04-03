import math
from typing import NamedTuple, Callable

from consts import SECTOR_SIZE, DAY
from network import NetworkState, INITIAL_PLEDGE_PROJECTION_PERIOD, SUPPLY_LOCK_TARGET

class SectorBunch(NamedTuple):
    power: int
    pledge: float

class BaseMinerState:
    """Miner with leased tokens but no pledge shortfall behaviour."""

    def __init__(self, balance: float):
        self.power: int = 0
        self.balance: float = balance
        self.lease: float = 0.0
        self.pledge_locked: float = 0.0

        self.reward_earned: float = 0.0
        self.fee_burned: float = 0.0
        self.lease_fee_accrued = 0.0

        # Scheduled expiration of power, by epoch.
        self._expirations: dict[int, list[SectorBunch]] = {}

    def summary(self, rounding=4):
        net_equity = self.balance - self.lease
        return {
            'power': self.power,
            'balance': round(self.balance, rounding),
            'lease': round(self.lease, rounding),
            'pledge_locked': round(self.pledge_locked, rounding),
            'available': round(self.available_balance(), rounding),
            'net_equity': round(net_equity, rounding),

            'reward_earned': round(self.reward_earned, rounding),
            'fee_burned': round(self.fee_burned, rounding),
            'lease_fee_accrued': round(self.lease_fee_accrued, rounding),
        }

    def available_balance(self) -> float:
        return self.balance - self.pledge_locked

    def max_pledge_for_tokens(self, net: NetworkState, available_lock: float) -> float:
        """The maximum incremental initial pledge commitment allowed for an incremental locking."""
        return available_lock

    def activate_sectors(self, net: NetworkState, power: int, duration: int, lock: float = float("inf")) -> (
            int, float):
        """
        Activates power and locks a specified pledge.
        Lock must be at least the pledge requirement; it's a parameter only so subclasses can be more generous.
        If available balance is insufficient for the specified locking, the tokens are leased.
        Returns the power and pledge locked.
        """
        assert power % SECTOR_SIZE == 0

        pledge_requirement = net.initial_pledge_for_power(power)

        if lock >= pledge_requirement:
            lock = pledge_requirement
        else:
            raise RuntimeError(f"lock {lock} is less than minimum pledge {pledge_requirement}")
        self._lease(max(lock - self.available_balance(), 0))

        self.power += power
        self.pledge_locked += lock
        expiration = net.epoch + duration
        self._expirations.setdefault(expiration, []).append(SectorBunch(power, pledge_requirement))

        return power, lock

    def receive_reward(self, net: NetworkState, reward: float):
        # Vesting is ignored.
        self._earn_reward(reward)

        # Repay lease if possible.
        self._repay(min(self.lease, self.available_balance()))

    def handle_epoch(self, net: NetworkState):
        """Executes end-of-epoch state updates"""
        # Accrue token lease fees.
        # The fee is added to the repayment obligation. If the miner has funds, it will pay it next epoch.
        fee = net.fee_for_token_lease(self.lease, 1)
        self._accrue_lease_fee(fee)

        # Expire power.
        expiring_now = self._expirations.pop(net.epoch, [])
        for sb in expiring_now:
            self.handle_expiration(sb)

    def handle_expiration(self, sectors: SectorBunch):
        self.power -= sectors.power
        self.pledge_locked -= sectors.pledge

    def _earn_reward(self, v: float):
        assert v >= 0
        self.balance += v
        self.reward_earned += v

    def _burn_fee(self, v: float):
        assert v >= 0
        assert v <= self.available_balance()
        self.balance -= v
        self.fee_burned += v

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

class RepayShortfallMinerState(BaseMinerState):
    """A miner that repays a shortfall, as well as paying a fee."""

    MAX_REPAYMENT_TERM = 365 * DAY
    MAX_REPAYMENT_REWARD_FRACTION = 0.75
    MAX_FEE_REWARD_FRACTION = 0.25
    MIN_REPAYMENT_TAKE_FRACTION = 0.25

    @staticmethod
    def factory(balance: float) -> Callable[[], BaseMinerState]:
        """Returns a function that creates new miner states."""
        return lambda: RepayShortfallMinerState(balance=balance)

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
        # TODO: this is coupled with the simplified expected_reward_for_power
        # TODO: add duration parameter = min (duration, MAX_REPAYMENT_TERM)
        return available_lock / (1 - self.MAX_REPAYMENT_REWARD_FRACTION * self.MAX_REPAYMENT_TERM * net.epoch_reward / (
                INITIAL_PLEDGE_PROJECTION_PERIOD * net.epoch_reward + SUPPLY_LOCK_TARGET * net.circulating_supply))

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

    def shortfall_fraction(self, net) -> float:
        """The current shortfall as a fraction of the maximum allowed."""
        max_shortfall = self.MAX_REPAYMENT_REWARD_FRACTION * net.expected_reward_for_power(self.power,
            self.MAX_REPAYMENT_TERM)
        actual_shortfall = self.pledge_required - self.pledge_locked
        shortfall_frac = 0.0
        if max_shortfall > 0:
            shortfall_frac = actual_shortfall / max_shortfall
        shortfall_frac = min(shortfall_frac, 1.0)  # Clamp in case of over-shortfall
        return shortfall_frac

class BurnShortfallMinerState(BaseMinerState):
    """A miner that burns an equivalent amount to the shortfall, but never pledges it."""

    MAX_SHORTFALL_FRACTION = 0.50
    MIN_FEE_TAKE_FRACTION = 0.25

    @staticmethod
    def factory(balance: float) -> Callable[[], BaseMinerState]:
        """Returns a function that creates new miner states."""
        return lambda: BurnShortfallMinerState(balance=balance)

    def __init__(self, balance: float):
        super().__init__(balance)
        self.fee_pending: float = 0

    def summary(self, rounding=4):
        summary = super().summary(rounding)
        summary.update({
            'fee_pending': round(self.fee_pending, rounding),
        })
        return summary

    # Override
    def max_pledge_for_tokens(self, net: NetworkState, available_lock: float) -> float:
        """The maximum incremental initial pledge commitment allowed for an incremental locking."""
        return available_lock / self.MAX_SHORTFALL_FRACTION

    # Overrides
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
        minimum_pledge = pledge_requirement * (1 - self.MAX_SHORTFALL_FRACTION)

        if lock == 0:
            lock = minimum_pledge
        elif lock > pledge_requirement:
            lock = pledge_requirement
        elif lock < minimum_pledge:
            raise RuntimeError(f"lock {lock} is less than minimum pledge {pledge_requirement}")
        self._lease(max(lock - self.available_balance(), 0))

        self.power += power
        self.pledge_locked += lock  # Only the initially locked amount is ever required to be pledged
        self.fee_pending += pledge_requirement - lock  # Pending fee captures the difference to the notional initial pledge

        expiration = net.epoch + duration
        self._expirations.setdefault(expiration, []).append(SectorBunch(power, lock))

        return power, lock

    # Override
    def receive_reward(self, net: NetworkState, reward: float):
        # Vesting is ignored.
        self._earn_reward(reward)

        # Calculate and burn shortfall fee
        if self.fee_pending > 0:
            collateral_target = self.pledge_locked + self.fee_pending
            collateral_pct = self.pledge_locked / collateral_target
            available_pct = collateral_pct * collateral_pct
            fee_take_rate = max(self.MIN_FEE_TAKE_FRACTION, 1 - available_pct)
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
        # Reduce the outstanding fee in proportion to the power represented.
        # XXX it's not clear that this is appropriate policy.
        remaining_power_frac = (self.power - sectors.power) / self.power
        self.fee_pending *= remaining_power_frac

        self.power -= sectors.power
        self.pledge_locked -= sectors.pledge
