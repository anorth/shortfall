from typing import NamedTuple

from consts import SECTOR_SIZE
from network import NetworkState

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

    def max_pledge_for_tokens(self, net: NetworkState, available_lock: float, duration: int) -> float:
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

