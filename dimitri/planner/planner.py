"""Generates and evaluates the alternatives available from a GameState.

Planner orchestrates the CandidateGenerator, Simulator, and Evaluator.
For each candidate action it simulates the result from the ORIGINAL
GameState and evaluates that hypothetical state. Candidates are
alternative futures, not a sequence: no candidate is simulated from
another candidate's resulting state.

It never selects, ranks, sorts, filters, or recommends candidates, never
breaks ties, and never executes actions. Every generated candidate is
returned in generation order. Selection belongs to the Executive
downstream. The input GameState is never mutated.
"""

from dimitri.models.game_state import GameState
from dimitri.planner.evaluator import Evaluator
from dimitri.planner.generator import CandidateGenerator
from dimitri.planner.planning import CandidateEvaluation, PlanningResult
from dimitri.planner.simulator import Simulator


class Planner:
    """Produces a PlanningResult evaluating every candidate action."""

    def __init__(
        self,
        generator: CandidateGenerator | None = None,
        simulator: Simulator | None = None,
        evaluator: Evaluator | None = None,
    ):
        self._generator = generator if generator is not None else CandidateGenerator()
        self._simulator = simulator if simulator is not None else Simulator()
        self._evaluator = evaluator if evaluator is not None else Evaluator()

    def plan(self, game_state: GameState) -> PlanningResult:
        """Return an evaluation of every candidate action in ``game_state``."""
        candidates = []
        for action in self._generator.generate(game_state):
            resulting_state = self._simulator.simulate(game_state, action)
            candidates.append(
                CandidateEvaluation(
                    action=action,
                    resulting_state=resulting_state,
                    evaluation=self._evaluator.evaluate(resulting_state),
                )
            )
        return PlanningResult(candidates=tuple(candidates))
