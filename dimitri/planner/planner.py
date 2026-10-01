"""Generates and evaluates the alternatives available from a GameState.

Planner orchestrates the CandidateGenerator, Simulator, and Evaluator.
Each generated action becomes a candidate Turn containing only that
action. Every planning pass also includes the idle turn, in which the
farmer and every known hand PASS and no market order is placed, so
doing nothing is always an alternative. For each candidate turn it
simulates the result from the ORIGINAL GameState and evaluates that
hypothetical state. Candidates are
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
from dimitri.planner.turn import Turn


class Planner:
    """Produces a PlanningResult evaluating every candidate turn."""

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
        """Return an evaluation of every candidate turn in ``game_state``.

        Candidates are the generated actions' turns in generation order,
        followed by the idle turn.
        """
        turns = [Turn.from_action(a) for a in self._generator.generate(game_state)]
        turns.append(idle_turn(game_state))
        candidates = []
        for turn in turns:
            resulting_state = self._simulator.simulate_turn(game_state, turn)
            candidates.append(
                CandidateEvaluation(
                    turn=turn,
                    resulting_state=resulting_state,
                    evaluation=self._evaluator.evaluate(resulting_state),
                )
            )
        return PlanningResult(candidates=tuple(candidates))


def idle_turn(game_state: GameState) -> Turn:
    """Return the turn in which every unit PASSes and no market order is placed.

    It holds one None (PASS) per hand currently on the farm, so the
    Operator writes an explicit PASS for each known hand.
    """
    return Turn(hands=(None,) * len(game_state.player.farm.hands))
