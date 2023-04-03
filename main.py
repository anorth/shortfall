import json
import sys
import time

import miner
from consts import DAY, YEAR
from network import MAINNET_FEB_2023
from sim import SimConfig, Simulator
from strategy import StrategyConfig

def main(args):
    # TODO: argument processing
    epochs = 3 * YEAR + 1
    stats_interval = DAY

    cfg = SimConfig(
        network=MAINNET_FEB_2023,
        strategy=StrategyConfig.pledge_limited(1000.0, 3 * YEAR, True),
        miner_factory=miner.RepayShortfallMinerState.factory(balance=0),
        # miner_factory=miner.BurnShortfallMinerState.factory(balance=0),
    )
    sim = Simulator(cfg)

    start_time = time.perf_counter()
    stats = sim.run_all(epochs, stats_interval)
    end_time = time.perf_counter()

    for s in stats:
        print(json.dumps(s))
    latency = end_time - start_time
    print("Simulated {} epochs in {:.1f} sec".format(epochs, latency))

if __name__ == '__main__':
    main(sys.argv)
