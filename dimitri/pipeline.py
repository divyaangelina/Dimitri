"""Connects Dimitri's layers into one observation-to-action pass.

    observation -> Observer  -> GameState
                -> Analyst   -> Analysis
                -> Planner   -> PlanningResult (candidates)
                -> Executive -> Decision
                -> Operator  -> Kaggriculture action dict

Pipeline is orchestration only. It hands each layer's output to the next
and returns the Operator's action dict unchanged. It never parses,
analyzes, generates, evaluates, ranks, or selects actions, and never
writes API actions itself; every one of those belongs to a layer above.

Failures are not swallowed: a malformed observation raises the
Observer's ParseError or ValidationError unchanged.
"""

from dimitri.analyst.analyst import Analyst
from dimitri.executive.executive import Executive
from dimitri.observer.observer import Observer
from dimitri.operator.operator import Operator
from dimitri.planner.planner import Planner


class Pipeline:
    """Runs one Kaggriculture observation through every Dimitri layer."""

    def __init__(
        self,
        observer: Observer | None = None,
        analyst: Analyst | None = None,
        planner: Planner | None = None,
        executive: Executive | None = None,
        operator: Operator | None = None,
    ):
        self._observer = observer if observer is not None else Observer()
        self._analyst = analyst if analyst is not None else Analyst()
        self._planner = planner if planner is not None else Planner()
        self._executive = executive if executive is not None else Executive()
        self._operator = operator if operator is not None else Operator()

    def run(self, observation: dict) -> dict:
        """Return the Kaggriculture action dict for ``observation``.

        The Planner always offers at least the idle turn, so the
        Executive always has a candidate to choose.

        Raises:
            ParseError: If ``observation`` cannot be parsed.
            ValidationError: If the parsed GameState is incomplete.
        """
        game_state = self._observer.observe(observation)
        # The Planner does not consume the Analysis yet; it is computed
        # here so the pipeline exercises the Analyst layer end to end.
        self._analyst.analyze(game_state)
        planning_result = self._planner.plan(game_state)
        decision = self._executive.decide(planning_result)
        return self._operator.execute(decision)
