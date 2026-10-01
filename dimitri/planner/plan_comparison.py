"""Reports the measurable differences between two PlanEvaluations.

A PlanComparison answers one question: what measurable differences
exist between two simulated plans? Every field is a plain arithmetic
difference, plan A's value minus plan B's.

PlanComparison does not determine which Plan is preferable. It never
ranks, scores, or selects plans, and never combines money and time into
a rate such as cash per day or ROI. Weighing money against time, risk,
or opportunity cost is left to a future strategic layer. Cash is bank
money only; unsold goods are never valued.

Plans are only comparable from the same decision point, so both
evaluations must start with the same cash on the same day.
"""

from dataclasses import dataclass

from dimitri.planner.plan_evaluation import PlanEvaluation


@dataclass(frozen=True)
class PlanComparison:
    """An immutable record of the differences between two PlanEvaluations.

    Each field is plan A's value minus plan B's.

    Attributes:
        ending_cash_difference: Difference in ending cash.
        cash_delta_difference: Difference in cash change over the plan.
            It equals ``ending_cash_difference``, since both plans start
            with the same cash.
        turns_elapsed_difference: Difference in game turns simulated.
        ending_day_difference: Difference in the day each plan ends on.
    """

    ending_cash_difference: int
    cash_delta_difference: int
    turns_elapsed_difference: int
    ending_day_difference: int


def compare_plans(evaluation_a: PlanEvaluation, evaluation_b: PlanEvaluation) -> PlanComparison:
    """Return the differences between two PlanEvaluations, A minus B.

    Performs no simulation or evaluation and modifies neither argument.

    Raises:
        TypeError: If either argument is not a PlanEvaluation.
        ValueError: If the evaluations start from different cash or on
            different days, so they cannot come from the same decision
            point.
    """
    for name, evaluation in (("evaluation_a", evaluation_a), ("evaluation_b", evaluation_b)):
        if not isinstance(evaluation, PlanEvaluation):
            raise TypeError(
                f"{name} must be a PlanEvaluation, got {type(evaluation).__name__}"
            )
    if evaluation_a.starting_cash != evaluation_b.starting_cash:
        raise ValueError(
            "Plans start with different cash "
            f"({evaluation_a.starting_cash} vs {evaluation_b.starting_cash}); "
            "only plans from the same decision point can be compared"
        )
    if evaluation_a.starting_day != evaluation_b.starting_day:
        raise ValueError(
            "Plans start on different days "
            f"({evaluation_a.starting_day} vs {evaluation_b.starting_day}); "
            "only plans from the same decision point can be compared"
        )
    return PlanComparison(
        ending_cash_difference=evaluation_a.ending_cash - evaluation_b.ending_cash,
        cash_delta_difference=evaluation_a.cash_delta - evaluation_b.cash_delta,
        turns_elapsed_difference=evaluation_a.turns_elapsed - evaluation_b.turns_elapsed,
        ending_day_difference=evaluation_a.ending_day - evaluation_b.ending_day,
    )
