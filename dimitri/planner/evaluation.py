"""Represents the accounting value of a single GameState.

An Evaluation records what a state is worth under Dimitri's current
accounting model. It separates the competition objective from
descriptive holdings: Kaggriculture scores each player by the money they
hold at the end of the season, so only cash counts toward the final
objective. Inventory value and seed replacement cost describe the state
but are not objective value, because unsold holdings earn nothing at the
end of the season.

An Evaluation describes one state only. It carries no judgement about
actions, and it never compares or ranks states. Comparison belongs to
the Executive downstream.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Evaluation:
    """An immutable accounting summary of one GameState.

    Attributes:
        cash: The player's current money.
        inventory_value: Total sale value of the player's inventory at
            current market prices. Items without a price contribute 0.
            Descriptive only; not part of final_objective_value.
        seed_cost: Total replacement cost of the player's held seeds at
            the fixed seed prices. Seeds of an unknown crop contribute 0.
            Descriptive only; not part of final_objective_value.
        final_objective_value: The value of this state under the
            competition's scoring rule: the money that would count
            toward the final score, which is cash.
    """

    cash: int
    inventory_value: int
    seed_cost: int
    final_objective_value: int
