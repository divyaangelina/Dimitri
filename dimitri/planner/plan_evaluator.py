"""Measures the economic result of a hypothetical Plan.

PlanEvaluator answers one question: what economic state would this Plan
leave us in? It simulates the Plan with ``Simulator.simulate_plan``,
which owns every state transition, and then reads cash and time from
the initial and final GameStates.

It never decides whether a Plan should be chosen: it does not score,
rank, compare, or select plans, and it never values unsold goods as
cash. The caller's GameState is never mutated, whether the plan
succeeds, is empty, or fails.
"""

from dimitri.models.game_state import GameState
from dimitri.planner.plan import Plan
from dimitri.planner.plan_evaluation import PlanEvaluation
from dimitri.planner.simulator import Simulator


class PlanEvaluator:
    """Produces a PlanEvaluation by simulating a Plan."""

    def __init__(self, simulator: Simulator | None = None):
        self._simulator = simulator if simulator is not None else Simulator()

    def evaluate_plan(self, game_state: GameState, plan: Plan) -> PlanEvaluation:
        """Return the cash and time result of playing ``plan`` from ``game_state``.

        Raises:
            ValueError: If a turn of the plan cannot be simulated, as
                raised by ``Simulator.simulate_plan``.
        """
        final_state = self._simulator.simulate_plan(game_state, plan)
        starting_cash = game_state.player.money
        ending_cash = final_state.player.money
        return PlanEvaluation(
            starting_cash=starting_cash,
            ending_cash=ending_cash,
            cash_delta=ending_cash - starting_cash,
            starting_day=game_state.day,
            ending_day=final_state.day,
            turns_elapsed=len(plan.turns),
        )
