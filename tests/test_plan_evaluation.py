"""Tests for PlanEvaluator and PlanEvaluation.

A PlanEvaluation is the factual cash and time result of simulating a
Plan: cash is the final state's bank money only, and elapsed time is the
number of turns actually simulated, never the horizon. It describes a
simulated outcome and never decides whether a plan is desirable.

Real-environment tests send a plan's turns to the installed Kaggriculture
environment through the Operator and compare the evaluation with the
game's own observation after the plan's last turn. Weed spawns and
town-shop unlocks, which are random and not simulated, are switched off.
"""

import copy
import dataclasses
import json
from pathlib import Path

import pytest

from dimitri.analyst.opportunity import Opportunity, OpportunityKind
from dimitri.executive.decision import Decision
from dimitri.observer.parser import parse
from dimitri.operator.operator import Operator
from dimitri.pipeline import Pipeline
from dimitri.planner.action import BUY_SEED, DROP, HARVEST, PLANT, SELL, WATER, Action
from dimitri.planner.plan import Plan
from dimitri.planner.plan_evaluation import PlanEvaluation
from dimitri.planner.plan_evaluator import PlanEvaluator
from dimitri.planner.planning import CandidateEvaluation
from dimitri.planner.simulator import Simulator
from dimitri.planner.turn import Turn

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"

WHEAT = Opportunity(OpportunityKind.WHEAT_PRODUCTION)
TOMATO = Opportunity(OpportunityKind.TOMATO_PRODUCTION)
HOLD = Opportunity(OpportunityKind.HOLD_CASH)

BUY_WHEAT_SEED = Turn(market=(Action(BUY_SEED, "WHEAT", 1),))


def _state(step=0, shed=None):
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)
    observation["step"] = step
    observation["day"], observation["hour"] = divmod(step, 24)
    if shed is not None:
        observation["private"]["shed"] = shed
    return parse(observation)


def _plan(turns, opportunity=WHEAT, horizon=None):
    turns = tuple(turns)
    return Plan(opportunity, turns=turns, horizon=len(turns) if horizon is None else horizon)


def _schedule(length, actions):
    return [actions.get(i, Turn()) for i in range(length)]


def _evaluate(state, plan):
    return PlanEvaluator().evaluate_plan(state, plan)


def _wheat_turns(*, sell):
    """Buy, plant, and water WHEAT for three days; harvest 2 and drop them."""
    actions = {
        0: BUY_WHEAT_SEED,
        1: Turn(farmer=Action(PLANT, "WHEAT")),
        2: Turn(farmer=Action(WATER)),
        25: Turn(farmer=Action(WATER)),
        49: Turn(farmer=Action(WATER)),
        50: Turn(farmer=Action(HARVEST)),
        51: Turn(farmer=Action(DROP)),
    }
    if sell:
        actions[52] = Turn(market=(Action(SELL, "WHEAT", 2),))
    return _schedule(53, actions)


def _tomato_turns():
    """Grow TOMATO for 12 days, harvesting and dropping each of its 4 productions, then sell."""
    actions = {
        0: Turn(market=(Action(BUY_SEED, "TOMATO", 1),)),
        1: Turn(farmer=Action(PLANT, "TOMATO")),
        **{24 * day + 2: Turn(farmer=Action(WATER)) for day in range(12)},
        **{24 * day + 3: Turn(farmer=Action(HARVEST)) for day in (8, 9, 10, 11)},
        **{24 * day + 4: Turn(farmer=Action(DROP)) for day in (8, 9, 10, 11)},
        24 * 11 + 5: Turn(market=(Action(SELL, "TOMATO", 4),)),
    }
    return _schedule(24 * 11 + 6, actions)


# --- the model -----------------------------------------------------------


def test_plan_evaluation_has_only_factual_fields():
    assert [f.name for f in dataclasses.fields(PlanEvaluation)] == [
        "starting_cash",
        "ending_cash",
        "cash_delta",
        "starting_day",
        "ending_day",
        "turns_elapsed",
    ]


def test_plan_evaluation_is_immutable():
    evaluation = _evaluate(_state(), _plan([BUY_WHEAT_SEED]))

    with pytest.raises(dataclasses.FrozenInstanceError):
        evaluation.ending_cash = 0


def test_plan_evaluation_is_distinct_from_candidate_evaluation():
    assert not issubclass(PlanEvaluation, CandidateEvaluation)
    assert {f.name for f in dataclasses.fields(CandidateEvaluation)} == {
        "turn",
        "resulting_state",
        "evaluation",
    }


# --- basic evaluation ----------------------------------------------------


def test_one_turn_plan():
    evaluation = _evaluate(_state(), _plan([BUY_WHEAT_SEED]))

    assert evaluation == PlanEvaluation(
        starting_cash=3000,
        ending_cash=2990,
        cash_delta=-10,
        starting_day=0,
        ending_day=0,
        turns_elapsed=1,
    )


def test_multi_turn_plan():
    turns = [BUY_WHEAT_SEED, Turn(farmer=Action(PLANT, "WHEAT")), Turn(farmer=Action(WATER))]

    evaluation = _evaluate(_state(), _plan(turns))

    assert (evaluation.cash_delta, evaluation.turns_elapsed) == (-10, 3)


def test_multi_day_plan():
    evaluation = _evaluate(_state(step=20), _plan([Turn()] * 30, opportunity=HOLD))

    assert (evaluation.starting_day, evaluation.ending_day) == (0, 2)
    assert evaluation.turns_elapsed == 30
    assert evaluation.cash_delta == 0


def test_evaluation_matches_the_simulated_final_state():
    state = _state()
    plan = _plan(_wheat_turns(sell=True))

    evaluation = _evaluate(state, plan)
    final = Simulator().simulate_plan(state, plan)

    assert evaluation.ending_cash == final.player.money
    assert evaluation.ending_day == final.day
    assert evaluation.turns_elapsed == final.step - state.step


def test_evaluator_uses_the_given_simulator():
    calls = []

    class _Recording(Simulator):
        def simulate_plan(self, game_state, plan):
            calls.append(plan)
            return super().simulate_plan(game_state, plan)

    plan = _plan([BUY_WHEAT_SEED])
    PlanEvaluator(simulator=_Recording()).evaluate_plan(_state(), plan)

    assert calls == [plan]


# --- cash ----------------------------------------------------------------


def test_buying_seeds_lowers_cash():
    evaluation = _evaluate(_state(), _plan([Turn(market=(Action(BUY_SEED, "MELON", 3),))]))

    assert evaluation.cash_delta == -3 * 80


def test_selling_the_harvest_raises_ending_cash():
    unsold = _evaluate(_state(), _plan(_wheat_turns(sell=False)))
    sold = _evaluate(_state(), _plan(_wheat_turns(sell=True)))

    # By step 52 town consumption has raised WHEAT from 25 to 27 a unit.
    assert unsold.cash_delta == -10
    assert sold.cash_delta == -10 + 2 * 27
    assert sold.ending_cash - unsold.ending_cash == 2 * 27


def test_cash_delta_covers_the_whole_plan():
    evaluation = _evaluate(_state(), _plan(_wheat_turns(sell=True)))

    assert evaluation.cash_delta == evaluation.ending_cash - evaluation.starting_cash
    assert evaluation.starting_cash == 3000


def test_unsold_inventory_is_not_cash():
    # The harvest sits in the shed, worth 54 at market, but it is not cash.
    evaluation = _evaluate(_state(), _plan(_wheat_turns(sell=False)))
    final = Simulator().simulate_plan(_state(), _plan(_wheat_turns(sell=False)))

    assert final.player.inventory.items["WHEAT"] == 2
    assert evaluation.ending_cash == final.player.money == 2990


def test_held_seeds_are_not_cash():
    evaluation = _evaluate(_state(), _plan([Turn(market=(Action(BUY_SEED, "WHEAT", 5),))]))

    assert evaluation.ending_cash == 3000 - 5 * 10


def test_selling_existing_shed_stock_is_counted():
    state = _state(shed={"EGG": 1})

    evaluation = _evaluate(state, _plan([Turn(market=(Action(SELL, "EGG", 1),))]))

    assert evaluation.cash_delta == Simulator().simulate_turn(
        state, Turn(market=(Action(SELL, "EGG", 1),))
    ).player.money - state.player.money
    assert evaluation.cash_delta > 0


# --- time ----------------------------------------------------------------


def test_horizon_does_not_change_turns_elapsed():
    evaluation = _evaluate(_state(), _plan([BUY_WHEAT_SEED], horizon=100))

    assert evaluation.turns_elapsed == 1
    assert evaluation.ending_day == 0


def test_ending_day_follows_the_simulated_clock():
    evaluation = _evaluate(_state(step=23), _plan([Turn()]))

    assert (evaluation.starting_day, evaluation.ending_day) == (0, 1)


# --- empty plans ---------------------------------------------------------


@pytest.mark.parametrize("horizon", [0, 24])
def test_empty_plan(horizon):
    state = _state(step=5)
    before = copy.deepcopy(state)

    evaluation = _evaluate(state, Plan(HOLD, turns=(), horizon=horizon))

    assert evaluation == PlanEvaluation(
        starting_cash=3000,
        ending_cash=3000,
        cash_delta=0,
        starting_day=0,
        ending_day=0,
        turns_elapsed=0,
    )
    assert state == before


# --- isolation and failure ----------------------------------------------


def test_evaluation_does_not_mutate_the_initial_state():
    state = _state()
    before = copy.deepcopy(state)

    _evaluate(state, _plan(_wheat_turns(sell=True)))

    assert state == before


def test_invalid_plan_propagates_the_simulation_error():
    plan = _plan([Turn(), Turn(farmer=Action(HARVEST))])

    with pytest.raises(ValueError, match="Plan turn 1: .*without a plant"):
        _evaluate(_state(), plan)


def test_failed_evaluation_does_not_mutate_the_initial_state():
    state = _state()
    before = copy.deepcopy(state)

    with pytest.raises(ValueError):
        _evaluate(state, _plan([BUY_WHEAT_SEED, Turn(farmer=Action(DROP))]))

    assert state == before


# --- regression: decisions are unchanged ---------------------------------


def test_pipeline_decision_is_unchanged():
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)

    assert Pipeline().run(observation) == {"farmer": ["PASS"], "hands": [], "market": []}


# --- the real environment ------------------------------------------------


def _play(plan):
    """Send ``plan.turns`` to a real game from step 0; return its observations."""
    kaggle_environments = pytest.importorskip("kaggle_environments")
    received = {}
    operator = Operator()

    def agent(obs):
        step = obs["step"]
        received[step] = copy.deepcopy(dict(obs))
        turn = plan.turns[step] if step < len(plan.turns) else Turn()
        return operator.execute(Decision(turn=turn))

    env = kaggle_environments.make(
        "kaggriculture",
        configuration={
            "episodeSteps": len(plan.turns) + 3,
            "weedSpawnChance": 0,
            "townShopUnlockInterval": 10_000,
            "seed": 17,
        },
        debug=True,
    )
    env.run([agent, "pass"])
    return received


def _assert_matches_environment(plan):
    received = _play(plan)
    start, end = parse(received[0]), parse(received[len(plan.turns)])

    evaluation = PlanEvaluator().evaluate_plan(start, plan)

    assert evaluation == PlanEvaluation(
        starting_cash=start.player.money,
        ending_cash=end.player.money,
        cash_delta=end.player.money - start.player.money,
        starting_day=start.day,
        ending_day=end.day,
        turns_elapsed=end.step - start.step,
    )
    return evaluation


def test_real_environment_empty_plan():
    evaluation = _assert_matches_environment(Plan(HOLD, turns=(), horizon=0))

    assert evaluation.cash_delta == 0


def test_real_environment_seed_purchase():
    evaluation = _assert_matches_environment(_plan([BUY_WHEAT_SEED]))

    assert evaluation.cash_delta == -10


def test_real_environment_wheat_plan():
    evaluation = _assert_matches_environment(_plan(_wheat_turns(sell=True)))

    assert evaluation.cash_delta == -10 + 2 * 27
    assert (evaluation.ending_day, evaluation.turns_elapsed) == (2, 53)


def test_real_environment_tomato_plan():
    evaluation = _assert_matches_environment(_plan(_tomato_turns(), TOMATO))

    assert evaluation.cash_delta > 0
    assert (evaluation.starting_day, evaluation.ending_day) == (0, 11)
