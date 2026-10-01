"""Scores a single GameState under Dimitri's current accounting model.

Evaluator answers one question: what is this state worth? It computes
the same accounting quantities the Analyst reports (cash, inventory
value, seed replacement cost) directly from the GameState, so it can
evaluate any state, including hypothetical ones from the Simulator,
without depending on the Analyst. The final objective value is the
state's cash, since Kaggriculture scores money at the end of the season.

It scores states, not actions. It never chooses, ranks, or compares
actions, calculates ROI, predicts prices, or simulates future states.
Selection belongs to the Executive downstream. The input GameState is
never mutated.
"""

from dimitri.models.game_state import GameState
from dimitri.planner.evaluation import Evaluation
from dimitri.utils.valuation import market_value, seed_cost


class Evaluator:
    """Produces a deterministic Evaluation for a GameState."""

    def evaluate(self, game_state: GameState) -> Evaluation:
        """Return the accounting Evaluation of ``game_state``."""
        prices = game_state.market.prices
        cash = game_state.player.money
        inventory_value = market_value(game_state.player.inventory.items, prices)
        return Evaluation(
            cash=cash,
            inventory_value=inventory_value,
            seed_cost=seed_cost(game_state.player.seeds),
            final_objective_value=cash,
        )

