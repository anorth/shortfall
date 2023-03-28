import collections
import decimal
import json
import sys
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Dict, List

from consts import EXBIBYTE, PEBIBYTE, DAY
from miner import MinerState
from network import NetworkState

def main(args):
    # TODO flags
    # epochs := flag.Int("epochs", math.MaxInt32, "epochs to simulate")
    epochs = 366 * DAY
    stats_interval = DAY

    # Establish decimal context for FIL tokens.
    # NOTE: A precision of 18 is not the same as 18 decimal places, it's precision of
    # the mantissa.
    # A fixed-point representation might be needed.
    c = decimal.getcontext()
    c.prec = 18

    cfg = Config(
        network_epoch=0,
        network_power=18 * EXBIBYTE,
        network_epoch_reward=Decimal("90"),
        network_circulating_supply=Decimal("439_000_000"),

        miner_balance=Decimal("10_000"),

        strategy_initial_power=1 * PEBIBYTE,
        strategy_initial_duration=365 * DAY,
    )
    sim = Simulator(cfg)

    start_time = time.perf_counter()
    stats = sim.run_all(epochs, stats_interval)
    end_time = time.perf_counter()

    for s in stats:
        print(json.dumps(s, cls=EnhancedJSONEncoder))
    latency = end_time - start_time
    print("Simulated {} epochs in {:.1f} sec".format(epochs, latency))

@dataclass
class Config:
    network_epoch: int
    network_power: int
    network_epoch_reward: Decimal
    network_circulating_supply: Decimal

    miner_balance: Decimal

    strategy_initial_power: int
    strategy_initial_duration: int

class Simulator:
    """A simulator for a single miner's strategy in a network context."""

    def __init__(self, cfg: Config):
        power_baseline = 0  # TODO: derive baseline from network epoch instead
        self.net = NetworkState(cfg.network_epoch, cfg.network_power, power_baseline, cfg.network_circulating_supply,
            cfg.network_epoch_reward)
        self.miner = MinerState(cfg.miner_balance)
        self.strategy = MinerStrategy(cfg.strategy_initial_power, cfg.strategy_initial_duration)
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
    # Power to onboard immediately.
    initial_onboard: int
    # Commitment duration for onboarding
    initial_duration: int
    # Whether initial onboarding is complete.
    initial_onboard_done: bool

    def __init__(self, initial_onboard: int, initial_duration: int):
        self.initial_onboard = initial_onboard
        self.initial_duration = initial_duration
        self.initial_onboard_done = False

    def act(self, net: NetworkState, m: MinerState):
        if not self.initial_onboard_done:
            m.activate_sectors(net, self.initial_onboard, self.initial_duration, pledge=Decimal(0))
            self.initial_onboard_done = True

class RewardEmitter:
    """An unrealistically smooth emission of a share of reward every epoch."""

    def emit(self, net: NetworkState, m: MinerState):
        share = net.epoch_reward * Decimal(m.power) / Decimal(net.power)
        m.receive_reward(net, share)

class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        else:
            return super().default(obj)

if __name__ == '__main__':
    main(sys.argv)
