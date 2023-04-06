import json
import sys
import time

from consts import DAY, YEAR
from miners.repay_proportional import RepayProportionalShortfallMinerState
from miners.burn import BurnShortfallMinerState
from miners.repay_ratchet import RepayRatchetShortfallMinerState
from network import *
from sim import SimConfig, Simulator
from strategy import StrategyConfig

def main(args):
    # TODO: argument processing
    epochs = 3 * YEAR + 1
    stats_interval = DAY

    # miner_factory=RepayProportionalShortfallMinerState.factory(balance=0),
    # miner_factory=BurnShortfallMinerState.factory(balance=0),
    miner_factory = RepayRatchetShortfallMinerState.factory(
        balance=0,
        max_repayment_term=3 * YEAR,
        max_fee_reward_fraction=0.25,
        reward_projection_decay=REWARD_DECAY + BASELINE_GROWTH
    )
    cfg = SimConfig(
        network=MAINNET_APR_2023,
        strategy=StrategyConfig.pledge_limited(1000.0, 3 * YEAR, True),
        miner_factory=miner_factory,
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
