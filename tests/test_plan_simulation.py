"""Tests for Simulator.simulate_plan: playing a Plan's turns in order.

simulate_plan plays each of ``plan.turns`` with play_turn on the state
the previous turn left, so time advances once per turn and every
end-of-turn effect applies. Only the listed turns are played; the
horizon is descriptive. The result is a hypothetical GameState, never a
judgement of the plan.

Real-environment tests send a plan's turns to the installed
Kaggriculture environment through the Operator and compare the final
observation with the simulated one. The two random effects the
Simulator does not model, weed spawns and town-shop unlocks, are
switched off in those games.
"""

import copy
import json
import time
from pathlib import Path

import pytest

from dimitri.analyst.opportunity import Opportunity, OpportunityKind
from dimitri.executive.decision import Decision
from dimitri.models.inventory import Inventory
from dimitri.models.tile import PlantTile
from dimitri.observer.parser import parse
from dimitri.operator.operator import Operator
from dimitri.pipeline import Pipeline
from dimitri.planner.action import (
    BUY_SEED,
    DROP,
    HARVEST,
    NORTH,
    PLANT,
    SELL,
    WATER,
    Action,
)
from dimitri.planner.plan import Plan
from dimitri.planner.planner import Planner
from dimitri.planner.simulator import Simulator
from dimitri.planner.turn import Turn

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"
SPAWN = (4, 4)

WHEAT = Opportunity(OpportunityKind.WHEAT_PRODUCTION)
TOMATO = Opportunity(OpportunityKind.TOMATO_PRODUCTION)
HOLD = Opportunity(OpportunityKind.HOLD_CASH)


def _state(step=0):
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)
    observation["step"] = step
    observation["day"], observation["hour"] = divmod(step, 24)
    return parse(observation)


def _plan(turns, opportunity=WHEAT, horizon=None):
    return Plan(opportunity, turns=tuple(turns), horizon=len(turns) if horizon is None else horizon)


def _schedule(length, actions):
    """Return ``length`` turns: ``actions[i]`` at game turn ``i``, idle elsewhere."""
    return [actions.get(i, Turn()) for i in range(length)]


def _spawn_tile(state):
    x, y = SPAWN
    return state.player.farm.tiles[y][x]


def _simulate(state, plan):
    return Simulator().simulate_plan(state, plan)


# --- basic simulation ----------------------------------------------------


def test_one_turn_plan_equals_play_turn():
    state = _state()
    turn = Turn(market=(Action(BUY_SEED, "WHEAT", 2),))

    assert _simulate(state, _plan([turn])) == Simulator().play_turn(state, turn)


def test_two_turn_plan_feeds_each_turn_the_previous_result():
    state = _state()
    turns = [Turn(market=(Action(BUY_SEED, "WHEAT", 1),)), Turn(farmer=Action(PLANT, "WHEAT"))]

    result = _simulate(state, _plan(turns))

    simulator = Simulator()
    assert result == simulator.play_turn(simulator.play_turn(state, turns[0]), turns[1])
    assert isinstance(_spawn_tile(result), PlantTile)
    assert result.player.seeds["WHEAT"] == 0


def test_later_turn_depends_on_earlier_turns():
    # PLANT alone would fail: the seed exists only after the first turn.
    plant = Turn(farmer=Action(PLANT, "WHEAT"))
    with pytest.raises(ValueError):
        _simulate(_state(), _plan([plant]))

    result = _simulate(_state(), _plan([Turn(market=(Action(BUY_SEED, "WHEAT", 1),)), plant]))
    assert _spawn_tile(result).crop == "WHEAT"


def test_buy_seed_plant_water():
    turns = [
        Turn(market=(Action(BUY_SEED, "WHEAT", 1),)),
        Turn(farmer=Action(PLANT, "WHEAT")),
        Turn(farmer=Action(WATER)),
    ]

    result = _simulate(_state(), _plan(turns))

    plant = _spawn_tile(result)
    assert (plant.planted_day, plant.watered_today) == (0, True)
    assert result.player.money == 3000 - 10


# --- time ----------------------------------------------------------------


@pytest.mark.parametrize("length", [0, 1, 5, 23, 24, 25, 60])
def test_time_advances_once_per_plan_turn(length):
    result = _simulate(_state(), _plan([Turn()] * length))

    assert (result.step, result.day, result.hour) == (length, length // 24, length % 24)


def test_plan_starting_mid_game_advances_from_its_start():
    result = _simulate(_state(step=22), _plan([Turn()] * 3))

    assert (result.step, result.day, result.hour) == (25, 1, 1)


def test_plan_crossing_a_day_boundary_applies_end_of_day():
    # The farmer walks away and carries nothing; at night it returns to spawn.
    state = _state(step=21)
    turns = [Turn(farmer=Action(NORTH)), Turn(farmer=Action(NORTH)), Turn(), Turn()]

    result = _simulate(state, _plan(turns))

    assert result.player.farm.farmer == list(SPAWN)
    assert (result.day, result.hour) == (1, 1)


def test_watering_state_resets_at_end_of_day():
    turns = _schedule(26, {
        0: Turn(market=(Action(BUY_SEED, "WHEAT", 1),)),
        1: Turn(farmer=Action(PLANT, "WHEAT")),
        2: Turn(farmer=Action(WATER)),
    })

    result = _simulate(_state(), _plan(turns))

    plant = _spawn_tile(result)
    assert (plant.watered_today, plant.consecutive_unwatered) == (False, 0)


def test_unwatered_new_plant_becomes_a_weed_overnight():
    turns = _schedule(24, {
        0: Turn(market=(Action(BUY_SEED, "WHEAT", 1),)),
        1: Turn(farmer=Action(PLANT, "WHEAT")),
    })

    result = _simulate(_state(), _plan(turns))

    assert type(_spawn_tile(result)).__name__ == "WeedTile"


def test_market_consumption_and_prices_evolve_over_the_plan():
    state = _state()

    result = _simulate(state, _plan([Turn()] * 13))

    # The town center consumes every product but FERTILIZER at steps 0 and 12.
    assert result.market.inventory["EGG"] == state.market.inventory["EGG"] - 2
    assert result.market.inventory["FERTILIZER"] == state.market.inventory["FERTILIZER"]
    assert result.market.prices["EGG"] >= state.market.prices["EGG"]


# --- crop lifecycle -----------------------------------------------------


def _watered_crop_turns(crop, days, extra=None):
    actions = {
        0: Turn(market=(Action(BUY_SEED, crop, 1),)),
        1: Turn(farmer=Action(PLANT, crop)),
        **{24 * day + 2: Turn(farmer=Action(WATER)) for day in range(days)},
    }
    actions.update(extra or {})
    return _schedule(24 * days, actions)


def test_wheat_grows_over_multiple_days():
    # Watering on days 2-4 of its age is inside WHEAT's window: +1 each.
    result = _simulate(_state(), _plan(_watered_crop_turns("WHEAT", 5)))

    plant = _spawn_tile(result)
    assert plant.yield_units == 1 + 3
    assert result.day == 5


def test_tomato_produces_across_multiple_days():
    # TOMATO produces at the end of days 7, 8, 9, 10; harvest each next morning.
    harvests = {24 * day + 3: Turn(farmer=Action(HARVEST)) for day in (8, 9, 10, 11)}
    drops = {24 * day + 4: Turn(farmer=Action(DROP)) for day in (8, 9, 10, 11)}

    result = _simulate(
        _state(), _plan(_watered_crop_turns("TOMATO", 12, {**harvests, **drops}), TOMATO)
    )

    assert result.player.inventory.items["TOMATO"] == 4
    assert isinstance(_spawn_tile(result), PlantTile)
    assert _spawn_tile(result).yield_units == 0


def test_carried_harvest_is_dropped_into_the_shed_at_night():
    turns = _watered_crop_turns("WHEAT", 3, {51: Turn(farmer=Action(HARVEST))})
    turns = turns[:72]

    result = _simulate(_state(), _plan(turns))

    assert result.player.inventory.items["WHEAT"] == 2
    assert result.player.unit_inventories == (Inventory(items={}),)


# --- plan semantics ------------------------------------------------------


def test_turn_order_is_preserved():
    buy = Turn(market=(Action(BUY_SEED, "WHEAT", 1),))
    plant = Turn(farmer=Action(PLANT, "WHEAT"))

    assert isinstance(_spawn_tile(_simulate(_state(), _plan([buy, plant]))), PlantTile)
    with pytest.raises(ValueError, match="Plan turn 0"):
        _simulate(_state(), _plan([plant, buy]))


def test_horizon_does_not_add_turns():
    turns = [Turn(market=(Action(BUY_SEED, "WHEAT", 1),))]

    short = _simulate(_state(), _plan(turns, horizon=1))
    long = _simulate(_state(), _plan(turns, horizon=500))

    assert long == short
    assert long.step == 1


def test_only_listed_turns_are_played():
    result = _simulate(_state(), _plan([Turn()] * 3, opportunity=HOLD, horizon=720))

    assert result.step == 3


# --- empty plans and isolation ------------------------------------------


def test_empty_plan_returns_an_unchanged_copy():
    state = _state(step=5)

    result = _simulate(state, Plan(HOLD, turns=(), horizon=0))

    assert result == state
    assert result is not state
    assert result.player.seeds is not state.player.seeds


def test_empty_plan_with_a_horizon_plays_nothing():
    state = _state(step=5)

    assert _simulate(state, Plan(HOLD, turns=(), horizon=48)) == state


def test_simulate_plan_does_not_mutate_the_initial_state():
    state = _state()
    before = copy.deepcopy(state)

    _simulate(state, _plan(_watered_crop_turns("WHEAT", 3)))

    assert state == before


def test_simulated_state_shares_nothing_mutable_with_the_initial_state():
    state = _state()

    result = _simulate(state, _plan([Turn(market=(Action(BUY_SEED, "WHEAT", 1),))]))
    result.player.seeds["WHEAT"] = 99
    result.player.farm.farmer.append(0)

    assert state.player.seeds["WHEAT"] == 0
    assert state.player.farm.farmer == list(SPAWN)


def test_same_plan_gives_the_same_result():
    plan = _plan(_watered_crop_turns("CARROT", 3))

    assert _simulate(_state(), plan) == _simulate(_state(), plan)


# --- errors --------------------------------------------------------------


def test_illegal_turn_raises_with_its_index():
    turns = [Turn(), Turn(), Turn(farmer=Action(HARVEST))]

    with pytest.raises(ValueError, match=r"Plan turn 2: .*without a plant"):
        _simulate(_state(), _plan(turns))


def test_illegal_turn_is_not_replaced_with_pass():
    turns = [Turn(market=(Action(BUY_SEED, "STRAWBERRY", 100),))]

    # 3000 buys 30 STRAWBERRY seeds: a partial fill is legal, as in play_turn.
    assert _simulate(_state(), _plan(turns)).player.seeds["STRAWBERRY"] == 30

    with pytest.raises(ValueError, match="Plan turn 1"):
        _simulate(_state(), _plan(turns * 2))


def test_failed_plan_does_not_mutate_the_initial_state():
    state = _state()
    before = copy.deepcopy(state)

    with pytest.raises(ValueError):
        _simulate(state, _plan([Turn(market=(Action(BUY_SEED, "WHEAT", 1),)), Turn(farmer=Action(DROP))]))

    assert state == before


# --- regression: decisions are unchanged ---------------------------------


def test_planner_does_not_simulate_plans():
    class _Refusing(Simulator):
        def simulate_plan(self, game_state, plan):
            raise AssertionError("the Planner must not simulate plans yet")

    Planner(simulator=_Refusing()).plan(_state())


def test_pipeline_decision_is_unchanged():
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)

    assert Pipeline().run(observation) == {"farmer": ["PASS"], "hands": [], "market": []}


# --- the real environment ------------------------------------------------


def _play_plan(plan):
    """Send ``plan.turns`` to a real game from step 0 via the Operator; return observations."""
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
            "seed": 13,
        },
        debug=True,
    )
    env.run([agent, "pass"])
    return received


def _assert_plan_matches_environment(plan):
    received = _play_plan(plan)
    start, end = parse(received[0]), parse(received[len(plan.turns)])

    predicted = Simulator().simulate_plan(start, plan)

    assert (predicted.step, predicted.day, predicted.hour) == (end.step, end.day, end.hour)
    assert predicted.player == end.player
    assert predicted.opponent == end.opponent
    assert predicted.market == end.market
    assert predicted.town == end.town
    return predicted


def test_real_environment_idle_plan():
    _assert_plan_matches_environment(_plan([Turn()] * 50, opportunity=HOLD))


def test_real_environment_wheat_plan():
    turns = _schedule(53, {
        0: Turn(market=(Action(BUY_SEED, "WHEAT", 1),)),
        1: Turn(farmer=Action(PLANT, "WHEAT")),
        2: Turn(farmer=Action(WATER)),
        25: Turn(farmer=Action(WATER)),
        49: Turn(farmer=Action(WATER)),
        50: Turn(farmer=Action(HARVEST)),
        51: Turn(farmer=Action(DROP)),
        52: Turn(market=(Action(SELL, "WHEAT", 2),)),
    })

    final = _assert_plan_matches_environment(_plan(turns))

    assert final.player.money > 3000 - 10
    assert final.player.inventory.items["WHEAT"] == 0
    assert _spawn_tile(final) is None


def test_real_environment_tomato_plan_over_multiple_productions():
    harvests = {24 * day + 3: Turn(farmer=Action(HARVEST)) for day in (8, 9, 10, 11)}
    drops = {24 * day + 4: Turn(farmer=Action(DROP)) for day in (8, 9, 10, 11)}
    sell = {24 * 11 + 5: Turn(market=(Action(SELL, "TOMATO", 4),))}
    turns = _watered_crop_turns("TOMATO", 12, {**harvests, **drops, **sell})

    final = _assert_plan_matches_environment(_plan(turns, TOMATO))

    assert final.player.inventory.items["TOMATO"] == 0
    assert final.player.money > 3000 - 50


def test_real_environment_plan_crossing_a_day_boundary():
    # Plant late on day 0, water, then walk away; night returns the farmer.
    turns = _schedule(30, {
        0: Turn(market=(Action(BUY_SEED, "CARROT", 2),)),
        20: Turn(farmer=Action(PLANT, "CARROT")),
        21: Turn(farmer=Action(WATER)),
        22: Turn(farmer=Action(NORTH)),
        26: Turn(farmer=Action(WATER)),
    })

    final = _assert_plan_matches_environment(_plan(turns))

    assert final.player.farm.farmer == list(SPAWN)
    assert _spawn_tile(final).consecutive_unwatered == 0


# --- performance (informational) -----------------------------------------


@pytest.mark.parametrize("length", [10, 100])
def test_plan_simulation_cost_is_reported(length, capsys):
    plan = _plan([Turn()] * length, opportunity=HOLD)
    state = _state()

    started = time.perf_counter()
    Simulator().simulate_plan(state, plan)
    elapsed = time.perf_counter() - started

    with capsys.disabled():
        print(f"\n  simulate_plan: {length} turns in {elapsed * 1000:.1f} ms")
    assert elapsed < 30
