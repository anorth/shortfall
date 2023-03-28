import dataclasses
import decimal
import json
import sys
from decimal import Decimal

from miner import MinerState
from network import NetworkState

EXBIBYTE = 1 << 60
DAY = 2880

def main(args):
    # TODO flags
    # epochs := flag.Int("epochs", math.MaxInt32, "epochs to simulate")
    epochs = 366 * DAY
    print_interval = 2880

    # Establish decimal context for FIL tokens.
    # NOTE: A precision of 18 is not the same as 18 decimal places, it's precision of
    # the mantissa.
    # A fixed-point representation might be needed.
    c = decimal.getcontext()
    c.prec = 18

    network_power = 10 * EXBIBYTE
    power_baseline = network_power
    epoch_reward = Decimal("90.0")
    circulating_supply = Decimal("439_000_000")
    net = NetworkState(0, network_power, power_baseline, circulating_supply, epoch_reward)

    balance = 10 * Decimal("1000")
    m = MinerState(balance)
    s = MinerStrategy(1 << 40, 365 * DAY)
    rew = RewardEmitter()

    # Loop over epochs
    first_epoch = net.epoch
    for epoch in range (first_epoch, epochs):
        net.epoch = epoch

        # Emit rewards according to power at start of epoch.
        rew.emit(net, m)

        # Execute miner strategy.
        s.act(net, m)

        # Perform automatic state updates.
        m.handle_epoch(net)

        if epoch % print_interval == 0:
            stats = {
                'day': epoch // DAY,
                'epoch': epoch,
            }
            stats.update(m.summary())
            j = json.dumps(stats, cls=EnhancedJSONEncoder)
            print(j)

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
            m.activate_sectors(net, self.initial_onboard, self.initial_duration)
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
