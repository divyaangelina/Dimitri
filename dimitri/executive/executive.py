"""Selects the single action Dimitri commits to from a PlanningResult.

Executive answers one question: which already-evaluated action should we
commit to? It chooses the candidate whose Evaluation has the greatest
total_liquid_value. Ties go to the earliest candidate, so selection is
deterministic given the Planner's deterministic candidate ordering.

It never generates, simulates, or evaluates candidates, never executes
actions, and never mutates the PlanningResult or any GameState within
it. Execution belongs to the Operator downstream.
"""

from dimitri.planner.action import Action
from dimitri.planner.planning import PlanningResult


class Executive:
    """Selects one Action from a PlanningResult."""

    def decide(self, planning_result: PlanningResult) -> Action:
        """Return the action of the highest-valued candidate.

        Ties are broken by candidate order: the first candidate with the
        greatest total_liquid_value wins.

        Raises:
            ValueError: If ``planning_result`` has no candidates.
        """
        if not planning_result.candidates:
            raise ValueError("Cannot decide without candidate actions")
        best = planning_result.candidates[0]
        for candidate in planning_result.candidates[1:]:
            if (
                candidate.evaluation.total_liquid_value
                > best.evaluation.total_liquid_value
            ):
                best = candidate
        return best.action
