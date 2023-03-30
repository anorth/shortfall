import json
import sys
import time

from consts import EXBIBYTE, DAY
from miner import MinerConfig
from network import NetworkConfig
from sim import SimConfig, Simulator
from strategy import StrategyConfig

MAINNET_FEB_2023 = NetworkConfig(
    epoch=0,
    power=int(18.74 * EXBIBYTE),
    epoch_reward=90.97,
    circulating_supply=439_000_000.0,
    token_lease_fee=0.20,
)

def main(args):
    # TODO: argument processing
    epochs = 366 * DAY
    stats_interval = DAY

    cfg = SimConfig(
        network=MAINNET_FEB_2023,
        miner=MinerConfig(balance=0),
        strategy=StrategyConfig.pledge_limited(1000.0, 365 * DAY, True)
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
