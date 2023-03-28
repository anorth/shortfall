from decimal import Decimal
from typing import NamedTuple

from network import NetworkState

SECTOR_SIZE = 32 << 30


class SectorBunch(NamedTuple):
    power: int
    pledge: Decimal

class MinerState:
    def __init__(self, balance: Decimal):
        self.balance: Decimal = balance
        self.power: int = 0
        self.initial_pledge: Decimal = Decimal(0)

        # Scheduled expiration of power, by epoch.
        self._expirations: dict[int, list[SectorBunch]] = {}

    def summary(self):
        return {
            'balance': self.balance,
            'power': self.power,
            'initial_pledge': self.initial_pledge
        }

    def available_balance(self) -> Decimal:
        return self.balance - self.initial_pledge

    def activate_sectors(self, net: NetworkState, power: int, duration: int):
        # Round the power to a multiple of sector size.
        power = SECTOR_SIZE * (power // SECTOR_SIZE)
        pledge_required = net.initial_pledge_for_power(power)
        available = self.available_balance()
        if available < pledge_required:
            raise RuntimeError("insufficient available balance")
        expiration = net.epoch + duration

        self.power += power
        self.initial_pledge += pledge_required
        self._expirations.setdefault(expiration, []).append(SectorBunch(power, pledge_required))

    def receive_reward(self, reward: Decimal):
        # Vesting is ignored.
        self.balance += reward

    def handle_epoch(self, net: NetworkState):
        """Executes end-of-epoch state updates"""
        expiring_now = self._expirations.get(net.epoch, [])
        for sb in expiring_now:
            self.power -= sb.power
            self.initial_pledge -= sb.pledge



