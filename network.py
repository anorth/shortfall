import math
from dataclasses import dataclass

from consts import DAY, SECTOR_SIZE, YEAR, EXBIBYTE

SUPPLY_LOCK_TARGET = 0.30

INITIAL_PLEDGE_PROJECTION_PERIOD = 20 * DAY

@dataclass
class NetworkConfig:
    epoch: int
    power: int
    epoch_reward: float
    circulating_supply: float
    # Fee p.a. on externally leased tokens.
    token_lease_fee: float

MAINNET_FEB_2023 = NetworkConfig(
    epoch=0,
    power=int(18.74 * EXBIBYTE),
    epoch_reward=90.97,
    circulating_supply=439_000_000.0,
    token_lease_fee=0.20,
)

# Reward at epoch = initial reward * (1-r)^(epochs)
REWARD_DECAY = 1 - math.exp(math.log(1/2)/(6*YEAR))

# BASELINE_INITIAL_VALUE = 2_888_888_880_000_000_000
# BASELINE_EXPONENT = math.exp(math.log(1+2.0)/(365*2880))

@dataclass
class NetworkState:
    epoch: int
    power: int
    power_baseline: int
    circulating_supply: float
    epoch_reward: float
    token_lease_fee: float

    def __init__(self, cfg: NetworkConfig):
        self.epoch = cfg.epoch
        self.power = cfg.power
        self.power_baseline = 0 # TODO: derive baseline from network epoch instead
        self.circulating_supply = cfg.circulating_supply
        self.epoch_reward = cfg.epoch_reward
        self.token_lease_fee = cfg.token_lease_fee

    def handle_epoch(self):
        self.epoch += 1
        self.epoch_reward *= (1-REWARD_DECAY)

    def initial_pledge_for_power(self, power: int) -> float:
        """The initial pledge requirement for an incremental power addition."""
        storage = self.expected_reward_for_power(power, INITIAL_PLEDGE_PROJECTION_PERIOD)
        consensus = self.circulating_supply * power * SUPPLY_LOCK_TARGET / max(self.power, self.power_baseline)
        return storage + consensus

    def power_for_initial_pledge(self, pledge: float) -> int:
        """The maximum power that can be committed for an incremental pledge."""
        rewards = self.projected_reward(self.epoch_reward, INITIAL_PLEDGE_PROJECTION_PERIOD)
        power = pledge * self.power / (rewards + self.circulating_supply * SUPPLY_LOCK_TARGET)
        return int((power // SECTOR_SIZE) * SECTOR_SIZE)

    def expected_reward_for_power(self, power: int, duration: int) -> float:
        """Projected rewards for some power over a period, taking reward decay into account."""
        # Note this doesn't use alpha/beta filter estimate or take baseline rewards into account.
        if self.power <= 0:
            return self.projected_reward(self.epoch_reward, duration)
        return self.projected_reward(self.epoch_reward * power / self.power, duration)

    def projected_reward(self, epoch_reward: float, duration: int) -> float:
        """Projects a per-epoch reward into the future, taking decay into account"""
        return epoch_reward * sum_over_exponential_decay(duration, REWARD_DECAY)

    def fee_for_token_lease(self, amount: float, duration: int) -> float:
        return amount * self.token_lease_fee * duration / YEAR


def sum_over_exponential_decay(duration: int, decay: float) -> float:
    # SUM[(1-r)^x] for x in 0..duration
    return (1 - math.pow(1 - decay, duration) + decay * math.pow(1 - decay, duration)) / decay