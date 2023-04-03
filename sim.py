from dataclasses import dataclass
from typing import Iterable, Dict, List, Callable

from consts import DAY

from miner import BaseMinerState
from network import NetworkConfig, NetworkState
from strategy import StrategyConfig, MinerStrategy

@dataclass
class SimConfig:
    network: NetworkConfig
    strategy: StrategyConfig
    miner_factory: Callable[[], BaseMinerState]

class Simulator:
    """A simulator for a single miner's strategy in a network context."""

    def __init__(self, cfg: SimConfig):
        self.net = NetworkState(cfg.network)
        self.strategy = MinerStrategy(cfg.strategy)
        self.rewards = RewardEmitter()
        self.miner = cfg.miner_factory()

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
        # Append a final stats summary
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

    def emit(self, net: NetworkState, m: BaseMinerState):
        share = net.epoch_reward * m.power / net.power
        m.receive_reward(net, share)
