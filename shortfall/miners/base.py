from collections import defaultdict
from typing import NamedTuple

from ..consts import SECTOR_SIZE
from ..network import NetworkState


class SectorBunch(NamedTuple):
    power: int
    pledge: float


# Fraction of earned rewards that are immediately available
AVAILABLE_REWARD_SHARE = 0.25
# Fraction of earned rewards that vest
VEST_REWARD_SHARE = 1 - AVAILABLE_REWARD_SHARE
# Interval between vesting chunks
VESTING_INTERVAL = 2800
# Number of intervals over which vesting occurs
VESTING_PERIOD_INTERVALS = 180

class BaseMinerState:
    """Miner with leased tokens but no pledge shortfall behaviour."""

    def __init__(self, balance: float):
        self.power: int = 0
        self.balance: float = balance
        self.lease: float = 0.0
        self.pledge_locked: float = 0.0
        self.vesting_locked: float = 0.0
        self.vesting_table: dict[int, float] = defaultdict(float)

        self.reward_earned: float = 0.0
        self.fee_burned: float = 0.0
        self.lease_fee_accrued = 0.0
        self.epochs: int = 0
        self.pledge_epochs: float = 0.0

        # Scheduled expiration of power, by epoch.
        self._expirations: dict[int, list[SectorBunch]] = defaultdict(list[SectorBunch])

    @staticmethod
    def factory(balance: float):
        """Returns a function that creates new miner states."""
        return lambda: BaseMinerState(balance=balance)

    def summary(self, rounding=4):
        net_equity = self.balance - self.lease
        # Time-weighted total return on pledge
        fofr = (self.reward_earned - self.fee_burned - self.lease_fee_accrued) / \
               (self.pledge_epochs / self.epochs)
        return {
            'power': self.power,
            'balance': round(self.balance, rounding),
            'lease': round(self.lease, rounding),
            'pledge_locked': round(self.pledge_locked, rounding),
            'vesting_locked': round(self.vesting_locked, rounding),
            'available': round(self.available_balance(), rounding),
            'net_equity': round(net_equity, rounding),
            'fofr': round(fofr, rounding),

            'reward_earned': round(self.reward_earned, rounding),
            'fee_burned': round(self.fee_burned, rounding),
            'lease_fee_accrued': round(self.lease_fee_accrued, rounding),
        }

    def available_balance(self) -> float:
        return self.balance - (self.pledge_locked + self.vesting_locked)

    def max_pledge_for_tokens(self, net: NetworkState, available_lock: float,
            duration: int) -> float:
        """The maximum nominal initial pledge commitment allowed for an incremental locking."""
        return available_lock

    def activate_sectors(self, net: NetworkState, power: int, duration: int,
            lock: float = float("inf")) -> (
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
        self._expirations[expiration].append(SectorBunch(power, pledge_requirement))

        return power, lock

    def receive_reward(self, net: NetworkState, reward: float):
        self._earn_reward(reward)
        self._vest_reward(net.epoch, reward)

        # Repay lease if possible.
        self._repay(min(self.lease, self.available_balance()))

    def handle_epoch(self, net: NetworkState):
        """Executes end-of-epoch state updates."""
        # Accrue token lease fees.
        # The fee is added to the repayment obligation. If the miner has funds, it will pay it next epoch.
        fee = net.fee_for_token_lease(self.lease, 1)
        self._accrue_lease_fee(fee)

        # Accumulate pledge epochs (for return-on-pledge calculation).
        self.epochs += 1
        self.pledge_epochs += self.pledge_locked

        # Expire power.
        expiring_now = self._expirations.pop(net.epoch, [])
        for sb in expiring_now:
            self.handle_expiration(sb)

        # Vest rewards
        vesting_now = self.vesting_table.pop(net.epoch, 0.0)
        if vesting_now > 0.0:
            self.handle_vest(vesting_now)

    def handle_expiration(self, sectors: SectorBunch):
        self.power -= sectors.power
        self.pledge_locked -= sectors.pledge

    def handle_vest(self, vested: float):
        """Accounts for earned rewards vesting."""
        self.vesting_locked -= vested

    def _earn_reward(self, v: float):
        """Accounts for earned reward."""
        assert v >= 0
        self.balance += v
        self.reward_earned += v

    def _vest_reward(self, epoch: int, v: float) -> float:
        """Locks part of an already-earned reward for vesting. Returns the immediately available amount."""
        assert v >= 0
        available_reward = v * AVAILABLE_REWARD_SHARE
        vesting_reward = v - available_reward
        self.vesting_locked += vesting_reward
        # This is slightly simplified from the real calculation, which handles
        # rounding error more robustly.
        each_vest = vesting_reward / VESTING_PERIOD_INTERVALS
        e = (epoch // VESTING_INTERVAL) * VESTING_INTERVAL + VESTING_INTERVAL
        while vesting_reward > 0.0:
            vest_amount = min(each_vest, vesting_reward)
            self.vesting_table[e] += vest_amount
            vesting_reward -= vest_amount
            e += VESTING_INTERVAL
        return available_reward

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
