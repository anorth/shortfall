from dataclasses import dataclass
from typing import NamedTuple
from decimal import Decimal

from network import NetworkState


@dataclass
class MinerState:
    balance: Decimal
    power: int = 0
    initial_pledge: Decimal = 0

    def available_balance(self) -> Decimal:
        return self.balance - self.initial_pledge

    def activate_sectors(self, net: NetworkState, power: int):
        pledge_required = net.initial_pledge_for_power(power)
        available = self.available_balance()
        if available < pledge_required:
            raise RuntimeError("insufficient available balance")

        self.power += power
        self.initial_pledge += pledge_required

    def receive_reward(self, reward: Decimal):
        # Vesting is ignored.
        self.balance += reward