import json
import sys
import time
from dataclasses import dataclass
from typing import Iterable, Dict, List

from consts import EXBIBYTE, PEBIBYTE, DAY
from miner import MinerState
from network import NetworkState

def main(args):
    # TODO: argument processing
    epochs = 366 * DAY
    stats_interval = DAY

    cfg = Config(
        network_epoch=0,
        network_power=18 * EXBIBYTE,
        network_epoch_reward=90.0,
        network_circulating_supply=439_000_000.0,

        miner_balance=10_000.0,

        strategy_max_power=10 * PEBIBYTE,
        strategy_max_power_onboard=10 * PEBIBYTE,
        strategy_max_pledge_onboard=10_000.0,
        strategy_commitment_duration=365 * DAY,
    )
    sim = Simulator(cfg)

    start_time = time.perf_counter()
    stats = sim.run_all(epochs, stats_interval)
    end_time = time.perf_counter()

    for s in stats:
        print(json.dumps(s))
    latency = end_time - start_time
    print("Simulated {} epochs in {:.1f} sec".format(epochs, latency))

@dataclass
class Config:
    network_epoch: int
    network_power: int
    network_epoch_reward: float
    network_circulating_supply: float

    miner_balance: float

    strategy_max_power: int
    strategy_max_power_onboard: int
    strategy_max_pledge_onboard: float
    strategy_commitment_duration: int

class Simulator:
    """A simulator for a single miner's strategy in a network context."""

    def __init__(self, cfg: Config):
        power_baseline = 0  # TODO: derive baseline from network epoch instead
        self.net = NetworkState(cfg.network_epoch, cfg.network_power, power_baseline, cfg.network_circulating_supply,
            cfg.network_epoch_reward)
        self.miner = MinerState(cfg.miner_balance)
        self.strategy = MinerStrategy(cfg.strategy_max_power, cfg.strategy_max_power_onboard,
            cfg.strategy_max_pledge_onboard, cfg.strategy_commitment_duration)
        self.rewards = RewardEmitter()

    def run(self, epochs, stats_interval=1) -> Iterable[Dict]:
        """
        Executes some epochs of simulation.
        This function is a generator, yielding statistics after each `stats_interval` epochs.
        """
        first_epoch = self.net.epoch
        for epoch in range(first_epoch, epochs):
            self.net.epoch = epoch

            # Emit rewards according to power at start of epoch.
            self.rewards.emit(self.net, self.miner)

            # Execute miner strategy.
            self.strategy.act(self.net, self.miner)

            # Perform automatic state updates.
            self.miner.handle_epoch(self.net)

            if epoch % stats_interval == 0:
                yield self.stats()

    def run_all(self, epochs, stats_interval=1) -> List[Dict]:
        """
        Executes some epochs of simulation to completion.
        Returns the statistics collected each stats_interval epochs, and at completion.
        """
        stats = list(self.run(epochs, stats_interval))
        if stats and stats[-1]['epoch'] != self.net.epoch:
            stats.append(self.stats())
        return stats

    def stats(self) -> Dict:
        stats = {
            'day': self.net.epoch // DAY,
            'epoch': self.net.epoch,
        }
        stats.update(self.miner.summary())
        return stats

class MinerStrategy:
    def __init__(self, max_power: int, max_power_onboard: int, max_pledge_onboard: float, commitment_duration: int):
        # The maximum amount of storage power available at any one time.
        self.max_power: int = max_power
        # The maximum total amount of onboarding to perform ever.
        # Prevents re-investment after this amount (even after power expires).
        self.max_power_onboard: int = max_power_onboard
        # The maximum total tokens to pledge ever.
        # Prevents re-investment after this amount (even after pledge is returned).
        self.max_pledge_onboard = max_pledge_onboard
        # Commitment duration for onboarded power.
        self.commitment_duration: int = commitment_duration

        self.take_shortfall = True
        self._onboarded = 0
        self._pledged = 0.0

    def act(self, net: NetworkState, m: MinerState):
        available_for_pledging = min(m.available_balance(), self.max_pledge_onboard - self._pledged)
        if self.take_shortfall:
            target_pledge = net.max_pledge_for_tokens(available_for_pledging)
        else:
            target_pledge = available_for_pledging

        target_power = min(self.max_power - m.power, net.power_for_initial_pledge(target_pledge))
        target_power = min(target_power, self.max_power_onboard - self._onboarded)

        if target_power > 0:
            power, pledge = m.activate_sectors(net, target_power, self.commitment_duration, pledge=m.available_balance())
            self._onboarded += power
            self._pledged += pledge

class RewardEmitter:
    """An unrealistically smooth emission of a share of reward every epoch."""

    def emit(self, net: NetworkState, m: MinerState):
        share = net.epoch_reward * m.power / net.power
        m.receive_reward(net, share)

# class EnhancedJSONEncoder(json.JSONEncoder):
#     def default(self, obj):
#         if isinstance(obj, Decimal):
#             return str(obj)
#         else:
#             return super().default(obj)

if __name__ == '__main__':
    main(sys.argv)
