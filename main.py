import dataclasses
import decimal
import json
import sys
from decimal import Decimal

from miner import MinerState
from network import NetworkState

EXBIBYTE = 1 << 60

def main(args):
    # TODO flags
    # epochs := flag.Int("epochs", math.MaxInt32, "epochs to simulate")
    epochs = 100

    # Establish decimal context for FIL tokens
    c = decimal.getcontext()
    c.prec = 18

    network_power = 10 * EXBIBYTE
    power_baseline = network_power
    epoch_reward = Decimal("90.0")
    circulating_supply = Decimal("439_000_000")
    net = NetworkState(network_power, power_baseline, circulating_supply, epoch_reward)

    balance = 10 * Decimal("1000")
    m = MinerState(balance)
    s = MinerStrategy(1 << 40)
    rew = RewardEmitter()

    # Loop over epochs
    for epoch in range (epochs):
        s.act(net, m)
        rew.emit(net, m)

        j = json.dumps(dataclasses.asdict(m), cls=EnhancedJSONEncoder)
        print(j)

class MinerStrategy:
    # Power to onboard immediately.
    initial_onboard: int
    # Whether initial onboarding is complete.
    initial_onboard_done: bool

    def __init__(self, initial_onboard: int):
        self.initial_onboard = initial_onboard
        self.initial_onboard_done = False

    def act(self, net: NetworkState, m: MinerState):
        if not self.initial_onboard_done:
            m.activate_sectors(net, self.initial_onboard)
            self.initial_onboard_done = True

class RewardEmitter:
    """An unrealistically smooth emission of a share of reward every epoch."""
    def emit(self, net: NetworkState, m: MinerState):
        share = Decimal(m.power) * net.epoch_reward / Decimal(net.power)
        m.receive_reward(share)


class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        else:
            return super().default(obj)

if __name__ == '__main__':
    main(sys.argv)
