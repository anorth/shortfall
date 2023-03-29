import json
import sys
import time
from dataclasses import dataclass
from typing import Iterable, Dict, List

from consts import EXBIBYTE, PEBIBYTE, DAY
from miner import MinerState
from network import NetworkState
from strategy import StrategyConfig, MinerStrategy

def main(args):
    # TODO: argument processing
    epochs = 366 * DAY
    stats_interval = DAY

    cfg = SimConfig(
        network_epoch=0,
        network_power=18 * EXBIBYTE,
        network_epoch_reward=90.0,
        network_circulating_supply=439_000_000.0,
        network_token_lease_fee=0.20,

        miner_balance=0,

        strategy=StrategyConfig(
            max_power=10 * PEBIBYTE,
            max_power_onboard=10 * PEBIBYTE,
            max_pledge_onboard=1_000.0,
            commitment_duration=365 * DAY,
            max_pledge_lease=1000,
            take_shortfall=True,
        )
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
class SimConfig:
    network_epoch: int
    network_power: int
    network_epoch_reward: float
    network_circulating_supply: float
    # Fee p.a. on externally leased tokens.
    network_token_lease_fee: float

    miner_balance: float

    strategy: StrategyConfig

class Simulator:
    """A simulator for a single miner's strategy in a network context."""

    def __init__(self, cfg: SimConfig):
        power_baseline = 0  # TODO: derive baseline from network epoch instead
        self.net = NetworkState(cfg.network_epoch, cfg.network_power, power_baseline, cfg.network_circulating_supply,
            cfg.network_epoch_reward, cfg.network_token_lease_fee)
        self.miner = MinerState(cfg.miner_balance)
        self.strategy = MinerStrategy(cfg.strategy)
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
