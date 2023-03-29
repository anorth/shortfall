from dataclasses import dataclass

from consts import SECTOR_SIZE
from miner import MinerState
from network import NetworkState

@dataclass
class StrategyConfig:
    # The maximum amount of storage power available at any one time.
    max_power: int
    # The maximum total amount of onboarding to perform ever.
    # Prevents re-investment after this amount (even after power expires).
    max_power_onboard: int
    # The maximum total tokens to pledge ever.
    # Prevents re-investment after this amount (even after pledge is returned).
    max_pledge_onboard: float
    # Commitment duration for onboarded power.
    commitment_duration: int
    # Maximum tokens to lease from external party.
    max_pledge_lease: float
    # Whether to use a pledge shortfall (always at maximum available).
    take_shortfall: bool

class MinerStrategy:
    def __init__(self, cfg: StrategyConfig):
        self.cfg = cfg
        self._onboarded = 0
        self._pledged = 0.0

    def act(self, net: NetworkState, m: MinerState):
        available_tokens = m.available_balance() + (self.cfg.max_pledge_lease - m.lease)
        available_pledge = min(available_tokens, self.cfg.max_pledge_onboard - self._pledged)
        if self.cfg.take_shortfall:
            target_pledge = net.max_pledge_for_tokens(available_pledge)
        else:
            target_pledge = available_pledge

        target_power = min(self.cfg.max_power - m.power, net.power_for_initial_pledge(target_pledge))
        target_power = min(target_power, self.cfg.max_power_onboard - self._onboarded)
        # Round power to a multiple of sector size.
        target_power = (target_power // SECTOR_SIZE) * SECTOR_SIZE

        if target_power > 0:
            power, pledge = m.activate_sectors(net, target_power, self.cfg.commitment_duration, pledge=available_tokens)
            self._onboarded += power
            self._pledged += pledge
