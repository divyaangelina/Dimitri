"""Tests for ContinuationEvaluator: projecting end-of-season bank cash.

From a state, the evaluator compares HOLD_CASH (keep the current cash)
with every generated plan followed by continuation from the state it
leaves, and keeps the branch with the greatest terminal bank cash. Every
branch runs to the same season endpoint.

Real-environment tests play the projected plan sequence in the installed
Kaggriculture environment to the end of the season and compare the
final reward, which is the player's bank money, with the projection.
Random weeds and town-shop unlocks are switched off, and the opponent
passes, matching the Simulator's assumptions.
"""

import copy
import dataclasses
import json
from dataclasses import replace
from pathlib import Path

import pytest

from dimitri.analyst.opportunity import Opportunity, OpportunityKind
from dimitri.executive.decision import Decision
from dimitri.observer.parser import parse
from dimitri.operator.operator import Operator
from dimitri.pipeline import Pipeline
from dimitri.planner.action import BUY_SEED, SELL, Action
from dimitri.planner.continuation import (
    ContinuationEvaluation,
    ContinuationEvaluator,
    turns_remaining,
)
from dimitri.planner.plan import Plan
from dimitri.planner.plan_generator import (
    PlanGenerator,
    TomatoPlanGenerator,
    WheatPlanGenerator,
)
from dimitri.planner.planner import Planner
from dimitri.planner.simulator import Simulator
from dimitri.planner.turn import Turn
from dimitri.utils.constants import LAST_ACTION_STEP

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"
WHEAT = Opportunity(OpportunityKind.WHEAT_PRODUCTION)
MARKET = Opportunity(OpportunityKind.MARKET_TRADE)

DAY_27 = 24 * 27  # One wheat cycle still fits.
DAY_28 = 24 * 28  # Too late for wheat.
DAY_24 = 24 * 24  # Two or more wheat cycles fit.


def _state(step=0, shed=None, money=None):
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)
    observation["step"] = step
    observation["day"], observation["hour"] = divmod(step, 24)
    if shed is not None:
        observation["private"]["shed"] = shed
    if money is not None:
        observation["farms"][observation["player"]]["money"] = money
    return parse(observation)


def _evaluate(state, generators=None):
    return ContinuationEvaluator(generators=generators).evaluate(state)


def _play_plans(state, plans):
    for plan in plans:
        state = Simulator().simulate_plan(state, plan)
    return state


class _FixedPlans(PlanGenerator):
    """Offers ``plans`` from ``at_step`` only, and nothing elsewhere."""

    opportunity_kind = OpportunityKind.MARKET_TRADE

    def __init__(self, plans, at_step=None):
        self._plans = tuple(plans)
        self._at_step = at_step
        self.calls = 0

    def generate(self, game_state, opportunity):
        self.calls += 1
        if self._at_step is not None and game_state.step != self._at_step:
            return ()
        return self._plans


class _Refusing(PlanGenerator):
    opportunity_kind = OpportunityKind.WHEAT_PRODUCTION

    def generate(self, game_state, opportunity):
        raise AssertionError("no plan should be generated")


def _market_plan(*turns):
    return Plan(MARKET, turns=turns, horizon=len(turns))


# --- the model -----------------------------------------------------------


def test_continuation_evaluation_fields():
    assert [f.name for f in dataclasses.fields(ContinuationEvaluation)] == [
        "starting_cash",
        "projected_terminal_cash",
        "turns_remaining",
        "continuation_plans_considered",
        "plans",
    ]


def test_continuation_evaluation_is_immutable():
    evaluation = _evaluate(_state(DAY_28))

    with pytest.raises(dataclasses.FrozenInstanceError):
        evaluation.projected_terminal_cash = 0


@pytest.mark.parametrize(
    ("step", "remaining"), [(0, 719), (1, 718), (LAST_ACTION_STEP, 1), (LAST_ACTION_STEP + 1, 0)]
)
def test_turns_remaining_counts_playable_turns(step, remaining):
    assert turns_remaining(_state(step)) == remaining


def test_default_policy_uses_the_wheat_and_tomato_generators():
    generators = ContinuationEvaluator()._generators

    assert [type(g) for g in generators] == [WheatPlanGenerator, TomatoPlanGenerator]


# --- HOLD_CASH -----------------------------------------------------------


def test_hold_cash_keeps_current_cash():
    evaluation = _evaluate(_state(), generators=())

    assert evaluation == ContinuationEvaluation(
        starting_cash=3000,
        projected_terminal_cash=3000,
        turns_remaining=719,
        continuation_plans_considered=0,
        plans=(),
    )


def test_season_end_terminates_without_generating():
    evaluation = _evaluate(_state(LAST_ACTION_STEP + 1), generators=[_Refusing()])

    assert (evaluation.projected_terminal_cash, evaluation.turns_remaining) == (3000, 0)
    assert evaluation.plans == ()


def test_late_game_without_time_for_wheat_holds_cash():
    evaluation = _evaluate(_state(DAY_28))

    assert (evaluation.projected_terminal_cash, evaluation.plans) == (3000, ())
    assert evaluation.continuation_plans_considered == 0


def test_unsold_inventory_is_not_counted_as_terminal_cash():
    # No configured generator sells EGG, so it stays unsold. (Shed wheat is
    # sold by WHEAT_PRODUCTION: see test_wheat_continuation.py.)
    evaluation = _evaluate(_state(DAY_28, shed={"EGG": 50}))

    assert evaluation.projected_terminal_cash == 3000


# --- WHEAT continuation --------------------------------------------------


def test_one_wheat_cycle_when_only_one_fits():
    state = _state(DAY_27)

    evaluation = _evaluate(state)

    (plan,) = evaluation.plans
    assert plan.opportunity == WHEAT
    assert evaluation.continuation_plans_considered == 1
    assert evaluation.projected_terminal_cash == Simulator().simulate_plan(state, plan).player.money
    assert evaluation.projected_terminal_cash > 3000


def test_no_wheat_continuation_without_money():
    evaluation = _evaluate(_state(DAY_27, money=5))

    assert (evaluation.projected_terminal_cash, evaluation.plans) == (5, ())


def test_repeated_wheat_cycles_when_time_permits():
    evaluation = _evaluate(_state(DAY_24))

    assert len(evaluation.plans) >= 2
    assert all(plan.opportunity == WHEAT for plan in evaluation.plans)


def test_each_plan_continues_from_the_previous_plans_result():
    state = _state(DAY_24)
    evaluation = _evaluate(state)

    for plan in evaluation.plans:
        assert WheatPlanGenerator().generate(state, WHEAT) == (plan,)
        state = Simulator().simulate_plan(state, plan)

    assert state.player.money == evaluation.projected_terminal_cash
    assert state.step <= LAST_ACTION_STEP + 1


def test_projection_is_the_final_bank_cash_of_the_plan_sequence():
    state = _state(DAY_24)
    evaluation = _evaluate(state)

    final = _play_plans(state, evaluation.plans)

    assert evaluation.projected_terminal_cash == final.player.money
    # Each wheat plan sells its own harvest, so no wheat is left over.
    assert final.player.inventory.items["WHEAT"] == 0


def test_full_season_from_the_start():
    # Wheat alone: a single chain of plans, one considered per state.
    evaluation = _evaluate(_state(), generators=[WheatPlanGenerator()])

    assert evaluation.turns_remaining == 719
    assert len(evaluation.plans) > 10
    assert evaluation.projected_terminal_cash > 3000
    assert evaluation.continuation_plans_considered == len(evaluation.plans)


# --- branching -----------------------------------------------------------


def test_losing_plan_is_not_chosen_over_holding_cash():
    losing = _market_plan(Turn(market=(Action(BUY_SEED, "MELON", 1),)))

    evaluation = _evaluate(_state(DAY_28), generators=[_FixedPlans([losing], at_step=DAY_28)])

    assert (evaluation.projected_terminal_cash, evaluation.plans) == (3000, ())
    assert evaluation.continuation_plans_considered == 1


def test_generated_plan_that_cannot_be_simulated_raises():
    # A generator must only return simulatable plans; this one offers a
    # seed purchase at every state until the money runs out.
    losing = _market_plan(Turn(market=(Action(BUY_SEED, "MELON", 1),)))

    with pytest.raises(ValueError, match="Cannot afford 'MELON'"):
        _evaluate(_state(DAY_28), generators=[_FixedPlans([losing])])


def test_higher_terminal_cash_branch_is_chosen():
    losing = _market_plan(Turn(market=(Action(BUY_SEED, "MELON", 1),)))
    state = _state(DAY_27)

    evaluation = _evaluate(state, generators=[_FixedPlans([losing], at_step=DAY_27), WheatPlanGenerator()])

    assert [p.opportunity for p in evaluation.plans] == [WHEAT]
    assert evaluation.continuation_plans_considered >= 2


def test_plans_of_different_lengths_are_compared_at_the_season_end():
    # Selling the egg now finishes sooner, and after one turn it is ahead
    # in cash. Waiting 30 turns lets the town center buy EGG from the
    # market, raising its price, so the later sale ends with more cash.
    state = _state(DAY_28, shed={"EGG": 1})
    sell_now = _market_plan(Turn(market=(Action(SELL, "EGG", 1),)))
    sell_later = _market_plan(*[Turn()] * 30, Turn(market=(Action(SELL, "EGG", 1),)))

    evaluation = _evaluate(state, generators=[_FixedPlans([sell_now, sell_later], at_step=DAY_28)])

    now, later = (Simulator().simulate_plan(state, p).player.money for p in (sell_now, sell_later))
    assert later > now
    assert evaluation.plans == (sell_later,)
    assert evaluation.projected_terminal_cash == later


def test_ties_keep_holding_cash():
    wait = _market_plan(Turn())

    evaluation = _evaluate(_state(DAY_28), generators=[_FixedPlans([wait], at_step=DAY_28)])

    assert evaluation.plans == ()


# --- safety --------------------------------------------------------------


def test_zero_turn_plans_are_ignored():
    empty = Plan(MARKET, turns=(), horizon=0)
    generator = _FixedPlans([empty])

    evaluation = _evaluate(_state(DAY_28), generators=[generator])

    assert evaluation.continuation_plans_considered == 0
    assert generator.calls == 1


def test_plans_running_past_the_season_are_rejected():
    too_long = _market_plan(*[Turn()] * 30)

    evaluation = _evaluate(_state(LAST_ACTION_STEP - 10), generators=[_FixedPlans([too_long])])

    assert evaluation.continuation_plans_considered == 0


def test_repeating_one_turn_plans_terminate_at_the_season_end():
    generator = _FixedPlans([_market_plan(Turn())])

    evaluation = _evaluate(_state(LAST_ACTION_STEP - 20), generators=[generator])

    # One plan per remaining turn along the only branch, then season end.
    assert evaluation.continuation_plans_considered == 21
    assert generator.calls == 21


def test_evaluation_does_not_mutate_the_state():
    state = _state(DAY_24)
    before = copy.deepcopy(state)

    _evaluate(state)

    assert state == before


def test_evaluation_is_deterministic():
    assert _evaluate(_state(DAY_24)) == _evaluate(_state(DAY_24))


# --- architecture: live decisions unchanged ------------------------------


def test_live_pipeline_does_not_use_continuation(monkeypatch):
    def _refuse(*args, **kwargs):
        raise AssertionError("the live pipeline must not project continuations")

    monkeypatch.setattr(ContinuationEvaluator, "evaluate", _refuse)
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)

    assert Pipeline().run(observation) == {"farmer": ["PASS"], "hands": [], "market": []}
    assert Planner().plan(parse(observation)).candidates[-1].turn == Turn()


# --- the real environment ------------------------------------------------


def _play_season(start_step, evaluator):
    """Pass until ``start_step``, then project from the live observation and play the plans.

    Returns the projection and the season's final bank money (the reward).
    """
    kaggle_environments = pytest.importorskip("kaggle_environments")
    operator = Operator()
    schedule = {}

    def agent(obs):
        step = obs["step"]
        if step == start_step:
            projection = evaluator.evaluate(parse(copy.deepcopy(dict(obs))))
            schedule["projection"] = projection
            turns = [turn for plan in projection.plans for turn in plan.turns]
            schedule.update({start_step + i: turn for i, turn in enumerate(turns)})
        return operator.execute(Decision(turn=schedule.get(step, Turn())))

    env = kaggle_environments.make(
        "kaggriculture",
        configuration={"weedSpawnChance": 0, "townShopUnlockInterval": 10_000, "seed": 29},
        debug=True,
    )
    env.run([agent, "pass"])
    return schedule["projection"], env.steps[-1][0].reward


def test_real_environment_hold_cash_from_the_start():
    projection, final_money = _play_season(0, ContinuationEvaluator(generators=()))

    assert projection.plans == ()
    assert projection.projected_terminal_cash == final_money == 3000


def test_real_environment_one_wheat_cycle():
    projection, final_money = _play_season(DAY_27, ContinuationEvaluator())

    assert len(projection.plans) == 1
    assert projection.projected_terminal_cash == final_money


def test_real_environment_too_late_for_wheat():
    projection, final_money = _play_season(DAY_28, ContinuationEvaluator())

    assert projection.plans == ()
    assert projection.projected_terminal_cash == final_money == 3000


def test_real_environment_repeated_wheat_cycles():
    projection, final_money = _play_season(DAY_24, ContinuationEvaluator())

    assert len(projection.plans) >= 2
    assert projection.projected_terminal_cash == final_money


def test_real_environment_full_season_from_the_start():
    projection, final_money = _play_season(0, ContinuationEvaluator())

    assert len(projection.plans) >= 2
    assert projection.projected_terminal_cash == final_money
    assert final_money > 3000
