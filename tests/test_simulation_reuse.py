"""Tests for reusing a generator's simulation in continuation evaluation.

A PlanGenerator can return GeneratedPlans through
``generate_with_states``: each plan with the exact state
``Simulator.simulate_plan`` would produce from it, when the generator
already simulated the plan while building it. The ContinuationEvaluator
reuses such a state and simulates only plans that arrive without one.
The projection itself must be unchanged.
"""

import copy
import dataclasses
import json
from dataclasses import replace
from pathlib import Path

import pytest

from dimitri.analyst.opportunity import Opportunity, OpportunityKind
from dimitri.observer.parser import parse
from dimitri.planner.action import BUY_SEED, Action
from dimitri.planner.continuation import ContinuationEvaluator
from dimitri.planner.plan import Plan
from dimitri.planner.plan_generator import (
    GeneratedPlan,
    PlanGenerator,
    TomatoPlanGenerator,
    WheatPlanGenerator,
)
from dimitri.planner.simulator import Simulator
from dimitri.planner.turn import Turn
from dimitri.utils.constants import LAST_ACTION_STEP

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"
WHEAT = Opportunity(OpportunityKind.WHEAT_PRODUCTION)
MARKET = Opportunity(OpportunityKind.MARKET_TRADE)


def _state(day=0):
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)
    observation["step"] = day * 24
    observation["day"], observation["hour"] = day, 0
    return parse(observation)


class _CountingSimulator(Simulator):
    def __init__(self):
        self.simulated_plans = []

    def simulate_plan(self, game_state, plan):
        self.simulated_plans.append(plan)
        return super().simulate_plan(game_state, plan)


class _PlansOnly(PlanGenerator):
    """Wraps a generator but exposes only ``generate``, never a resulting state."""

    def __init__(self, inner):
        self._inner = inner
        self.opportunity_kind = inner.opportunity_kind

    def generate(self, game_state, opportunity):
        return self._inner.generate(game_state, opportunity)


# --- GeneratedPlan -------------------------------------------------------


def test_generated_plan_is_immutable():
    (generated,) = WheatPlanGenerator().generate_with_states(_state(), WHEAT)

    with pytest.raises(dataclasses.FrozenInstanceError):
        generated.resulting_state = None


def test_wheat_resulting_state_is_exactly_the_simulated_plan():
    for day in (0, 11, 24, 27):
        state = _state(day)

        (generated,) = WheatPlanGenerator().generate_with_states(state, WHEAT)

        assert generated.resulting_state == Simulator().simulate_plan(state, generated.plan)


def test_generate_returns_the_same_plans_as_generate_with_states():
    state = _state(5)

    assert WheatPlanGenerator().generate(state, WHEAT) == tuple(
        g.plan for g in WheatPlanGenerator().generate_with_states(state, WHEAT)
    )


def test_generate_with_states_mutates_nothing():
    state = _state(3)
    before = copy.deepcopy(state)

    (generated,) = WheatPlanGenerator().generate_with_states(state, WHEAT)

    assert state == before
    assert generated.resulting_state is not state


def test_wheat_generation_no_longer_resimulates_its_plan():
    simulator = _CountingSimulator()

    (plan,) = WheatPlanGenerator(simulator).generate(_state(), WHEAT)

    # Building the plan plays its turns; no separate validation replay.
    assert simulator.simulated_plans == []
    Simulator().simulate_plan(_state(), plan)


def test_wheat_still_returns_nothing_when_no_valid_plan_exists():
    assert WheatPlanGenerator().generate_with_states(_state(28), WHEAT) == ()
    assert WheatPlanGenerator().generate_with_states(_state(), MARKET) == ()


def test_default_generate_with_states_attaches_no_state():
    plan = Plan(MARKET, turns=(Turn(),), horizon=1)

    class _Fixed(PlanGenerator):
        opportunity_kind = OpportunityKind.MARKET_TRADE

        def generate(self, game_state, opportunity):
            return (plan,)

    assert _Fixed().generate_with_states(_state(), MARKET) == (GeneratedPlan(plan, None),)


# --- ContinuationEvaluator reuse ----------------------------------------


@pytest.mark.parametrize(
    ("day", "cash"), [(0, 8005), (15, 5246), (24, 3100), (27, 3048), (28, 3000)]
)
def test_projection_is_unchanged(day, cash):
    assert ContinuationEvaluator().evaluate(_state(day)).projected_terminal_cash == cash


@pytest.mark.parametrize("day", [0, 15, 24, 27, 28])
def test_reused_states_give_the_same_evaluation_as_simulating(day):
    state = _state(day)
    reusing = ContinuationEvaluator().evaluate(state)
    simulating = ContinuationEvaluator(
        generators=[_PlansOnly(WheatPlanGenerator()), _PlansOnly(TomatoPlanGenerator())]
    ).evaluate(state)

    # Identical cash, counts, and every concrete plan.
    assert reusing == simulating


def test_evaluator_does_not_resimulate_plans_with_known_states():
    simulator = _CountingSimulator()
    evaluator = ContinuationEvaluator(simulator=simulator)

    evaluation = evaluator.evaluate(_state(24))

    assert len(evaluation.plans) >= 2
    assert simulator.simulated_plans == []


def test_evaluator_simulates_plans_without_known_states():
    simulator = _CountingSimulator()
    evaluator = ContinuationEvaluator(
        simulator=simulator, generators=[_PlansOnly(WheatPlanGenerator(simulator))]
    )

    evaluation = evaluator.evaluate(_state(24))

    assert simulator.simulated_plans == list(evaluation.plans)


def test_mixed_generators_simulate_only_stateless_plans():
    losing = Plan(MARKET, turns=(Turn(market=(Action(BUY_SEED, "MELON", 1),)),), horizon=1)

    class _LosingOnce(PlanGenerator):
        opportunity_kind = OpportunityKind.MARKET_TRADE

        def generate(self, game_state, opportunity):
            return (losing,) if game_state.step == 24 * 27 else ()

    simulator = _CountingSimulator()
    evaluation = ContinuationEvaluator(
        simulator=simulator, generators=[_LosingOnce(), WheatPlanGenerator(simulator)]
    ).evaluate(_state(27))

    assert simulator.simulated_plans == [losing]
    assert [p.opportunity for p in evaluation.plans] == [WHEAT]


def test_recursion_starts_from_the_selected_plans_simulated_state():
    seen = []

    class _Recording(ContinuationEvaluator):
        def evaluate(self, game_state):
            seen.append(game_state)
            return super().evaluate(game_state)

    start = _state(24)
    evaluation = _Recording().evaluate(start)

    state = start
    for plan in evaluation.plans:
        state = Simulator().simulate_plan(state, plan)
        assert state in seen


def test_hold_cash_and_season_end_are_unchanged():
    assert ContinuationEvaluator(generators=()).evaluate(_state()).projected_terminal_cash == 3000

    past_end = replace(_state(), step=LAST_ACTION_STEP + 1, day=29, hour=23)
    evaluation = ContinuationEvaluator().evaluate(past_end)
    assert (evaluation.turns_remaining, evaluation.plans) == (0, ())


def test_evaluation_does_not_mutate_the_state():
    state = _state(15)
    before = copy.deepcopy(state)

    ContinuationEvaluator().evaluate(state)

    assert state == before


def test_evaluator_does_not_mutate_reused_generator_states():
    (generated,) = WheatPlanGenerator().generate_with_states(_state(24), WHEAT)
    before = copy.deepcopy(generated.resulting_state)

    class _Fixed(PlanGenerator):
        opportunity_kind = OpportunityKind.WHEAT_PRODUCTION

        def generate(self, game_state, opportunity):
            return ()

        def generate_with_states(self, game_state, opportunity):
            return (generated,) if game_state.step == 24 * 24 else ()

    ContinuationEvaluator(generators=[_Fixed(), WheatPlanGenerator()]).evaluate(_state(24))

    assert generated.resulting_state == before


def test_plans_past_the_season_are_still_rejected_with_states():
    turns = (Turn(),) * 30
    plan = Plan(MARKET, turns=turns, horizon=30)
    near_end = replace(_state(), step=LAST_ACTION_STEP - 10, day=29, hour=12)

    class _TooLong(PlanGenerator):
        opportunity_kind = OpportunityKind.MARKET_TRADE

        def generate(self, game_state, opportunity):
            return ()

        def generate_with_states(self, game_state, opportunity):
            return (GeneratedPlan(plan, Simulator().simulate_plan(game_state, plan)),)

    evaluation = ContinuationEvaluator(generators=[_TooLong()]).evaluate(near_end)

    assert evaluation.continuation_plans_considered == 0
