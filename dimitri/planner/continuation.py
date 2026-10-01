"""Projects a GameState forward to the end of the season.

ContinuationEvaluator answers one question: starting from this state,
what bank cash can Dimitri project for the end of the season using the
planning capabilities it currently has? Terminal bank cash is the
competition's objective, so it is the only quantity compared.

The continuation policy considers:

- HOLD_CASH, always: take no further action, so the season ends with
  the current bank cash.
- Every concrete plan from the configured PlanGenerators. By default
  that is WheatPlanGenerator (WHEAT_PRODUCTION) and TomatoPlanGenerator
  (TOMATO_PRODUCTION), in that order. Continuation is
  reconsidered from the state each plan leaves, so repeated cycles and
  reinvestment arise without being hard-coded. That state is reused
  when the generator already simulated the plan, and otherwise
  simulated here with ``Simulator.simulate_plan``.

Every branch is followed to the season's end, so plans of different
lengths are compared by the cash they lead to at the same endpoint,
never by their own cash change. Only bank cash counts: unsold goods and
seeds are not wealth. When branches tie, the earlier one is kept, with
HOLD_CASH first, so the projection is deterministic.

Termination: every accepted plan has at least one turn, ends by the
season's last playable step, and must advance the clock. A state past
the last playable step ends immediately at its current cash.

The projection is deterministic under the Simulator's assumptions (an
idle opponent, no random weeds or town-shop unlocks). It is a model
estimate, not a guaranteed outcome. Nothing in the live decision
pipeline uses it yet.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from dimitri.analyst.opportunity import Opportunity
from dimitri.models.game_state import GameState
from dimitri.planner.plan import Plan
from dimitri.planner.plan_generator import (
    GeneratedPlan,
    PlanGenerator,
    TomatoPlanGenerator,
    WheatPlanGenerator,
)
from dimitri.planner.simulator import Simulator
from dimitri.utils.constants import LAST_ACTION_STEP


@dataclass(frozen=True)
class ContinuationEvaluation:
    """An immutable projection of a GameState's end-of-season bank cash.

    Attributes:
        starting_cash: The bank cash in the evaluated state.
        projected_terminal_cash: The greatest end-of-season bank cash
            reachable with the continuation policy, under the Simulator's
            deterministic assumptions.
        turns_remaining: The playable turns left in the season from the
            evaluated state (0 once past the last playable step).
        continuation_plans_considered: How many concrete plans were
            simulated across every branch of the projection.
        plans: The concrete plans, in order, whose play reaches
            ``projected_terminal_cash``, each starting where the previous
            ended. Empty when holding cash is projected to do as well.
    """

    starting_cash: int
    projected_terminal_cash: int
    turns_remaining: int
    continuation_plans_considered: int
    plans: tuple[Plan, ...]


def turns_remaining(game_state: GameState) -> int:
    """Return how many playable turns remain in the season from ``game_state``."""
    return max(0, LAST_ACTION_STEP + 1 - game_state.step)


class ContinuationEvaluator:
    """Projects end-of-season bank cash from HOLD_CASH and generated plans."""

    def __init__(
        self,
        simulator: Simulator | None = None,
        generators: Sequence[PlanGenerator] | None = None,
    ):
        self._simulator = simulator if simulator is not None else Simulator()
        self._generators = (
            tuple(generators)
            if generators is not None
            else (
                WheatPlanGenerator(self._simulator),
                TomatoPlanGenerator(self._simulator),
            )
        )

    def evaluate(self, game_state: GameState) -> ContinuationEvaluation:
        """Return the projected end-of-season cash from ``game_state``.

        ``game_state`` is never mutated.

        Raises:
            ValueError: If a generated plan cannot be simulated, which
                breaks the PlanGenerator contract.
        """
        cash = game_state.player.money
        remaining = turns_remaining(game_state)
        best = ContinuationEvaluation(cash, cash, remaining, 0, ())
        if remaining == 0:
            return best

        considered = 0
        for generated in self._plans(game_state):
            plan = generated.plan
            resulting_state = generated.resulting_state
            if resulting_state is None:
                resulting_state = self._simulator.simulate_plan(game_state, plan)
            if resulting_state.step <= game_state.step:
                continue
            continuation = self.evaluate(resulting_state)
            considered += 1 + continuation.continuation_plans_considered
            if continuation.projected_terminal_cash > best.projected_terminal_cash:
                best = ContinuationEvaluation(
                    cash,
                    continuation.projected_terminal_cash,
                    remaining,
                    0,
                    (plan, *continuation.plans),
                )
        return ContinuationEvaluation(
            best.starting_cash,
            best.projected_terminal_cash,
            best.turns_remaining,
            considered,
            best.plans,
        )

    def _plans(self, game_state: GameState) -> list[GeneratedPlan]:
        """Return every generated plan that has turns and fits in the season."""
        plans = []
        for generator in self._generators:
            opportunity = Opportunity(generator.opportunity_kind)
            for generated in generator.generate_with_states(game_state, opportunity):
                last_step = game_state.step + len(generated.plan.turns) - 1
                if generated.plan.turns and last_step <= LAST_ACTION_STEP:
                    plans.append(generated)
        return plans
