"""Represents the complete turn Dimitri has committed to.

A Decision marks the boundary between choosing and doing. The Planner
proposes candidate Turns (as CandidateEvaluations); the Executive
selects one and wraps it in a Decision; the Operator accepts only a
Decision and writes its Turn in the Kaggriculture API format.

It reuses the Planner's Turn rather than defining a second turn
representation. It carries no alternatives, scores, or ranking, and no
API formatting: it records only what was committed to.
"""

from dataclasses import dataclass

from dimitri.planner.turn import Turn


@dataclass(frozen=True)
class Decision:
    """An immutable record of the turn the Executive committed to.

    Attributes:
        turn: The selected candidate Turn, unchanged.
    """

    turn: Turn
