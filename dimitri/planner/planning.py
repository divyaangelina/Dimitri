"""Represents the Planner's evaluated alternatives for one GameState.

A CandidateEvaluation pairs one candidate Action with the hypothetical
GameState it would produce and that state's Evaluation. A PlanningResult
holds every CandidateEvaluation for a single planning pass, in the order
the CandidateGenerator produced the actions.

These are representations only. They carry no selection, ranking, or
recommendation: every alternative is kept and none is preferred.
Choosing among them belongs to the Executive downstream.
"""

from dataclasses import dataclass

from dimitri.models.game_state import GameState
from dimitri.planner.action import Action
from dimitri.planner.evaluation import Evaluation


@dataclass(frozen=True)
class CandidateEvaluation:
    """An immutable record of one alternative future.

    Attributes:
        action: The candidate action considered.
        resulting_state: The hypothetical GameState immediately after
            taking ``action`` from the original GameState.
        evaluation: The Evaluation of ``resulting_state``.
    """

    action: Action
    resulting_state: GameState
    evaluation: Evaluation


@dataclass(frozen=True)
class PlanningResult:
    """An immutable collection of every evaluated candidate.

    Attributes:
        candidates: One CandidateEvaluation per generated action, in
            generation order. Empty when no actions are available.
    """

    candidates: tuple[CandidateEvaluation, ...]
