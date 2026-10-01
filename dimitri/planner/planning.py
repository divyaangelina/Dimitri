"""Represents the Planner's evaluated alternatives for one GameState.

A CandidateEvaluation pairs one candidate Turn with the hypothetical
GameState it would produce and that state's Evaluation. A PlanningResult
holds every CandidateEvaluation for a single planning pass, in the order
the Planner produced the turns.

These are representations only. They carry no selection, ranking, or
recommendation: every alternative is kept and none is preferred.
Choosing among them belongs to the Executive downstream.
"""

from dataclasses import dataclass

from dimitri.models.game_state import GameState
from dimitri.planner.evaluation import Evaluation
from dimitri.planner.turn import Turn


@dataclass(frozen=True)
class CandidateEvaluation:
    """An immutable record of one alternative future.

    Attributes:
        turn: The candidate turn considered.
        resulting_state: The hypothetical GameState immediately after
            taking ``turn`` from the original GameState.
        evaluation: The Evaluation of ``resulting_state``.
    """

    turn: Turn
    resulting_state: GameState
    evaluation: Evaluation


@dataclass(frozen=True)
class PlanningResult:
    """An immutable collection of every evaluated candidate.

    Attributes:
        candidates: One CandidateEvaluation per candidate turn, in
            generation order. Empty when no actions are available.
    """

    candidates: tuple[CandidateEvaluation, ...]
