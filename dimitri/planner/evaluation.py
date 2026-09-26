"""Represents the accounting value of a single GameState.

An Evaluation records what a state is worth under Dimitri's current
accounting model: cash on hand, the market value of held inventory,
and the replacement cost of held seeds. It describes one state only.
It carries no judgement about actions, and it never compares or ranks
states. Comparison belongs to the Executive downstream.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Evaluation:
    """An immutable accounting summary of one GameState.

    Attributes:
        cash: The player's current money.
        inventory_value: Total sale value of the player's inventory at
            current market prices. Items without a price contribute 0.
        seed_cost: Total replacement cost of the player's held seeds at
            current market prices. Seeds without a price contribute 0.
            Reported separately; seeds are an asset, not a debt, so this
            is not subtracted from total_liquid_value.
        total_liquid_value: cash + inventory_value.
    """

    cash: int
    inventory_value: int
    seed_cost: int
    total_liquid_value: int
