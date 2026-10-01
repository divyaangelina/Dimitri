"""Represents the factual economic result of simulating one Plan.

A PlanEvaluation records what a hypothetical multi-turn Plan would do
to Dimitri's cash and how much game time it would take, as measured on
the states before and after ``Simulator.simulate_plan``.

It describes what happened in simulation. It does not decide whether the
Plan is desirable: it carries no score, ranking, recommendation, risk,
or expected value. Cash is bank money only, since Kaggriculture scores
money at the end of the season; unsold goods and held seeds are not
counted as cash.

It is distinct from CandidateEvaluation, which evaluates one immediate
executable Turn for the current decision.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanEvaluation:
    """An immutable record of a simulated Plan's cash and time.

    Attributes:
        starting_cash: The player's money before the plan.
        ending_cash: The player's money in the simulated final state.
        cash_delta: ``ending_cash - starting_cash``, over the whole plan.
        starting_day: The in-game day before the plan.
        ending_day: The in-game day in the simulated final state.
        turns_elapsed: The number of game turns simulated, which is the
            number of turns in the plan, never its horizon.
    """

    starting_cash: int
    ending_cash: int
    cash_delta: int
    starting_day: int
    ending_day: int
    turns_elapsed: int
