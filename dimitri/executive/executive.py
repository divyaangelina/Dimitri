"""Selects the complete turn Dimitri commits to from a PlanningResult.

Executive answers one question: which already-evaluated turn should we
commit to? It chooses the candidate whose Evaluation has the greatest
final_objective_value. Ties go to the earliest candidate, so selection is
deterministic given the Planner's deterministic candidate ordering.

It never generates, simulates, or evaluates candidates, never executes
actions, and never mutates the PlanningResult or any GameState within
it. The selected Turn is returned wrapped in a Decision; writing it in
the Kaggriculture API format and executing it belong to the Operator
downstream.
"""

from dimitri.executive.decision import Decision
from dimitri.planner.planning import PlanningResult


class Executive:
    """Selects one candidate from a PlanningResult as a Decision."""

    def decide(self, planning_result: PlanningResult) -> Decision:
        """Return a Decision for the turn of the highest-valued candidate.

        Ties are broken by candidate order: the first candidate with the
        greatest final_objective_value wins.

        Raises:
            ValueError: If ``planning_result`` has no candidates.
        """
        if not planning_result.candidates:
            raise ValueError("Cannot decide without candidate actions")
        best = planning_result.candidates[0]
        for candidate in planning_result.candidates[1:]:
            if (
                candidate.evaluation.final_objective_value
                > best.evaluation.final_objective_value
            ):
                best = candidate
        return Decision(turn=best.turn)
