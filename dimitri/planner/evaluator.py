"""Scores a single GameState under Dimitri's current accounting model.

Evaluator answers one question: what is this state worth? It computes
the same accounting quantities the Analyst reports (cash, inventory
value, seed replacement cost) directly from the GameState, so it can
evaluate any state, including hypothetical ones from the Simulator,
without depending on the Analyst.

It scores states, not actions. It never chooses, ranks, or compares
actions, calculates ROI, predicts prices, or simulates future states.
Selection belongs to the Executive downstream. The input GameState is
never mutated.
"""

from collections.abc import Mapping

from dimitri.models.game_state import GameState
from dimitri.planner.evaluation import Evaluation


class Evaluator:
    """Produces a deterministic Evaluation for a GameState."""

    def evaluate(self, game_state: GameState) -> Evaluation:
        """Return the accounting Evaluation of ``game_state``."""
        prices = game_state.market.prices
        cash = game_state.player.money
        inventory_value = _priced_total(game_state.player.inventory.items, prices)
        seed_cost = _priced_total(game_state.player.seeds, prices)
        return Evaluation(
            cash=cash,
            inventory_value=inventory_value,
            seed_cost=seed_cost,
            total_liquid_value=cash + inventory_value,
        )


def _priced_total(quantities: Mapping[str, int], prices: Mapping[str, int]) -> int:
    """Sum quantity * price over the entries that have a market price."""
    return sum(
        quantity * prices[name]
        for name, quantity in quantities.items()
        if name in prices
    )
