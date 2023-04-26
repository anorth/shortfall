from dataclasses import dataclass

from .consts import SECTOR_SIZE, EXBIBYTE
from .miners.base import BaseMinerState
from .network import NetworkState


@dataclass
class StrategyConfig:
    # The maximum amount of storage power available at any one time.
    max_power: int
    # The maximum total amount of onboarding to perform ever.
    # Prevents re-investment after this amount (even after power expires).
    max_power_onboard: int
    # The maximum total tokens to lock as pledge ever.
    # Prevents re-investment after this amount (even after pledge is returned).
    max_pledge_onboard: float
    # Commitment duration for onboarded power.
    commitment_duration: int
    # Maximum tokens to lease from external party at any one time.
    max_pledge_lease: float
    # How much shortfall to take, as a fraction in [0, 1.0] of nominal pledge requirement.
    # The value 1.0 means take maximum available shortfall.
    use_shortfall: float

    @staticmethod
    def power_limited(power: int, duration: int, shortfall: float):
        """
        A strategy limited by power onboarding rather than tokens.
        The miner will onboard the configured power, borrowing any tokens needed for pledge.
        If shortfall is True, the miner will borrow only the minimum tokens required to lock.
        """
        return StrategyConfig(
            max_power=power,
            max_power_onboard=power,
            max_pledge_onboard=1e18,
            commitment_duration=duration,
            max_pledge_lease=1e28,
            use_shortfall=shortfall,
        )

    @staticmethod
    def pledge_limited(pledge: float, duration: int, shortfall: float):
        """
        A strategy limited by locked tokens rather than power.
        The miner will borrow any tokens needed up to the configured pledge, and then onboard as much power as possible.
        If shortfall is True, the miner will lock the same amount, but commit maximum allowed power.
        """
        return StrategyConfig(
            max_power=1000 * EXBIBYTE,
            max_power_onboard=1000 * EXBIBYTE,
            max_pledge_onboard=pledge,
            commitment_duration=duration,
            max_pledge_lease=1e18,
            use_shortfall=shortfall,
        )

    @staticmethod
    def pledge_lease_limited(lease: float, commitment: int, shortfall: float):
        """A strategy limited by pledge tokens borrowable."""
        return StrategyConfig(
            max_power=1000 * EXBIBYTE,
            max_power_onboard=1000 * EXBIBYTE,
            max_pledge_onboard=1e18,
            commitment_duration=commitment,
            max_pledge_lease=lease,
            use_shortfall=shortfall,
        )


class MinerStrategy:
    def __init__(self, cfg: StrategyConfig):
        assert 0 <= cfg.use_shortfall <= 1.0
        self.cfg = cfg
        self._onboarded = 0
        self._pledged = 0.0

    def act(self, net: NetworkState, m: BaseMinerState):
        available_lock = m.available_balance() + (self.cfg.max_pledge_lease - m.lease)
        available_lock = min(available_lock, self.cfg.max_pledge_onboard - self._pledged)
        if self.cfg.use_shortfall == 1.0:
            available_pledge = m.max_pledge_for_tokens(net, available_lock,
                self.cfg.commitment_duration)
        else:
            available_pledge = available_lock / (1 - self.cfg.use_shortfall)

        target_power = min(self.cfg.max_power - m.power, self.cfg.max_power_onboard - self._onboarded)
        power_for_pledge = net.power_for_initial_pledge(available_pledge)

        # Set power and lock amounts depending on which is the limiting factor.
        if target_power <= power_for_pledge:
            # Limited by power, attempt to take exactly the specified shortfall.
            # This may fail if the specified shortfall is greater than allowed.
            nominal_pledge = net.initial_pledge_for_power(target_power)
            # Note if use_shortfall == 1.0, this specifies locking zero, giving maximum shortfall.
            lock = nominal_pledge * (1.0 - self.cfg.use_shortfall)
        else:
            # Limited by pledge, lock all available.
            lock = available_lock
            target_power = power_for_pledge

        # Round power to a multiple of sector size.
        target_power = (target_power // SECTOR_SIZE) * SECTOR_SIZE

        if target_power > 0:
            power, pledge = m.activate_sectors(net, target_power, self.cfg.commitment_duration, lock=lock)
            self._onboarded += power
            self._pledged += pledge
