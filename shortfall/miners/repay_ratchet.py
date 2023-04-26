from typing import Callable

from ..consts import DAY, SECTOR_SIZE
from ..miners.base import BaseMinerState, SectorBunch
from ..network import NetworkState, INITIAL_PLEDGE_PROJECTION_PERIOD, SUPPLY_LOCK_TARGET, BASELINE_GROWTH, REWARD_DECAY

class RepayRatchetShortfallMinerState(BaseMinerState):
    """
    A miner that repays a shortfall, as well as paying a fee.
    The fraction of rewards taken for repayment ratchets only upwards as shortfall increases,
    ensuring the amount is repaid on time.
    """

    # See comments in __init__.
    DEFAULT_MAX_REPAYMENT_TERM = 3 * 365 * DAY
    DEFAULT_MAX_FEE_REWARD_FRACTION = 0.25
    DEFAULT_REWARD_PROJECTION_DECAY = REWARD_DECAY + BASELINE_GROWTH

    @staticmethod
    def factory(balance: float,
            max_repayment_term=DEFAULT_MAX_REPAYMENT_TERM,
            max_fee_reward_fraction=DEFAULT_MAX_FEE_REWARD_FRACTION,
            reward_projection_decay=DEFAULT_REWARD_PROJECTION_DECAY,
    ) -> Callable[[], BaseMinerState]:
        """Returns a function that creates new miner states."""
        return lambda: RepayRatchetShortfallMinerState(
            balance=balance,
            max_repayment_term=max_repayment_term,
            max_fee_reward_fraction=max_fee_reward_fraction,
            reward_projection_decay=reward_projection_decay
        )

    def __init__(self, balance: float,
            max_repayment_term=DEFAULT_MAX_REPAYMENT_TERM,
            max_fee_reward_fraction=DEFAULT_MAX_FEE_REWARD_FRACTION,
            reward_projection_decay=DEFAULT_REWARD_PROJECTION_DECAY,
    ):
        """
        :param balance: initial token balance
        :param max_repayment_term: maximum target term for which pledge expected to be fully repaid (if longer than commitment duration)
        :param max_fee_reward_fraction: maximum fraction of earned rewards to burn as fees
        :param reward_projection_decay: decay rate to use for projected rewards.
            - REWARD_DECAY assumes constant share of power and no change in satisfaction of baseline.
            - REWARD_DECAY+BASELINE_GROWTH assumes this miner stops while the rest of the network grows at the baseline rate
        """
        super().__init__(balance)
        self._max_repayment_term= max_repayment_term
        self._max_fee_reward_fraction = max_fee_reward_fraction
        self._max_repayment_reward_fraction = 1 - max_fee_reward_fraction
        self._reward_projection_decay = reward_projection_decay

        self.pledge_required: float = 0
        self.repayment_take_rate: float = 0

    def summary(self, rounding=4):
        shortfall = self.pledge_required - self.pledge_locked
        # Shortfall as a fraction of pledge required for the sectors committed.
        shortfall_pct = 0
        if self.pledge_required > 0:
            shortfall_pct = round(100 * shortfall / self.pledge_required, 2)
        summary = super().summary(rounding)
        summary.update({
            'pledge_required': round(self.pledge_required, rounding),
            'shortfall': round(shortfall, rounding),
            'shortfall_pct': shortfall_pct,
        })
        return summary

    # Override
    def max_pledge_for_tokens(self, net: NetworkState, available_lock: float, duration: int) -> float:
        """The maximum nominal initial pledge commitment allowed for an incremental locking."""
        duration = min(duration, self._max_repayment_term)
        return available_lock / \
            (1 - self._max_repayment_reward_fraction * net.projected_reward(net.epoch_reward, duration,
                decay=self._reward_projection_decay) /
             (net.projected_reward(net.epoch_reward,
                 INITIAL_PLEDGE_PROJECTION_PERIOD) + SUPPLY_LOCK_TARGET * net.circulating_supply))

    # Override
    def activate_sectors(self, net: NetworkState, power: int, duration: int, lock: float = float("inf")) -> (
            int, float):
        """
        Activates power and locks a specified pledge.
        Lock may be 0, meaning to lock the minimum (after shortfall), or inf to lock the full pledge requirement.
        If available balance is insufficient for the specified locking, the tokens are leased.
        Returns the power and pledge locked.
        """
        assert power % SECTOR_SIZE == 0

        pledge_requirement = net.initial_pledge_for_power(power)
        # This incremental limit on taking shortfall isn't an essential part of this construction.
        # We could just set a fixed parameter like 50%, and only constrain that the miner's total
        # reward (e.g. from existing sectors) are sufficient to repay on time.
        # This would advantage existing SPs who could leverage their power more than new SPs.
        incremental_shortfall = self._max_repayment_reward_fraction * net.expected_reward_for_power(
            power, min(duration, self._max_repayment_term), decay=self._reward_projection_decay)
        minimum_pledge = pledge_requirement - incremental_shortfall

        if lock == 0:
            lock = minimum_pledge
        elif lock > pledge_requirement:
            lock = pledge_requirement
        elif lock < minimum_pledge:
            raise RuntimeError(f"lock {lock} is less than minimum pledge {minimum_pledge}")
        self._lease(max(lock - self.available_balance(), 0))

        self.power += power
        self.pledge_required += pledge_requirement
        self.pledge_locked += lock

        expiration = net.epoch + duration
        self._expirations[expiration].append(SectorBunch(power, pledge_requirement))

        # Compute the repayment take from SP's current rewards needed to repay total shortfall in term.
        # Repayment take depends on shortest duration, so only update if this new sector actually took a shortfall.
        # This allows SP to onboard shorter sectors with full pledge without pessimistically increasing repayments.
        if lock < pledge_requirement:
            current_shortfall = self.pledge_required - self.pledge_locked
            expected_rewards = net.expected_reward_for_power(self.power, self._max_repayment_term,
                decay=self._reward_projection_decay)
            repayment_take_rate = current_shortfall / expected_rewards
            if repayment_take_rate > self._max_repayment_reward_fraction:
                raise RuntimeError(f"miner computed repayment reward fraction exceeds maximum")
            # Ratchet repayment take up if necessary.
            self.repayment_take_rate = max(self.repayment_take_rate, repayment_take_rate)

        return power, lock

    # Override
    def receive_reward(self, net: NetworkState, reward: float):
        # Vesting is ignored.
        self._earn_reward(reward)

        # Calculate shortfall rate as parameter to repayment and fee.
        assert self._max_fee_reward_fraction + self._max_repayment_reward_fraction <= 1.0
        shortfall_frac = self.shortfall_fraction(net)

        if shortfall_frac > 0:
            # Burn the fee
            fee_take_rate = shortfall_frac * self._max_fee_reward_fraction
            fee_amount = reward * fee_take_rate
            self._burn_fee(fee_amount)

            # Lock repayments as satisfied pledge.
            shortfall = self.pledge_required - self.pledge_locked
            repayment_amount = reward * self.repayment_take_rate
            if repayment_amount >= shortfall:
                repayment_amount = shortfall
                self.repayment_take_rate = 0  # Reset
            self.pledge_locked += repayment_amount
            assert fee_amount + repayment_amount <= reward

        # Repay lease if possible.
        self._repay(min(self.lease, self.available_balance()))

    # Override
    def handle_expiration(self, sectors: SectorBunch):
        pledge_satisfaction = self.pledge_locked / self.pledge_required
        pledge_to_release = pledge_satisfaction * sectors.pledge

        self.power -= sectors.power
        self.pledge_required -= sectors.pledge
        self.pledge_locked -= pledge_to_release

    def shortfall_fraction(self, net: NetworkState) -> float:
        """The current shortfall as a fraction of the maximum allowed."""
        max_shortfall = self._max_repayment_reward_fraction * net.expected_reward_for_power(self.power,
            self._max_repayment_term, decay=self._reward_projection_decay)
        actual_shortfall = self.pledge_required - self.pledge_locked
        shortfall_frac = 0.0
        if max_shortfall > 0:
            shortfall_frac = actual_shortfall / max_shortfall
        shortfall_frac = min(shortfall_frac, 1.0)  # Clamp in case of over-shortfall
        return shortfall_frac
