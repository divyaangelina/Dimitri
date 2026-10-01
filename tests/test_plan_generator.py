"""Tests for PlanGenerator and the WHEAT_PRODUCTION plan generator.

A PlanGenerator builds concrete Plans for one kind of Opportunity; it
never evaluates, ranks, or chooses them. The wheat generator builds one
complete plan: buy a seed, walk to the plot and plant, water daily,
harvest when ready, walk to the shed, drop, and sell the harvest.

Real-environment tests generate a plan from a live observation, send its
turns through the Operator, and compare the game's final state with
``Simulator.simulate_plan``. Weed spawns and town-shop unlocks, which are
random and not simulated, are switched off.
"""

import copy
import json
from pathlib import Path

import pytest

from dimitri.analyst.opportunity import Opportunity, OpportunityKind
from dimitri.executive.decision import Decision
from dimitri.models.tile import PlantTile
from dimitri.observer.parser import parse
from dimitri.operator.operator import Operator
from dimitri.pipeline import Pipeline
from dimitri.planner.action import (
    BUY_SEED,
    DROP,
    EAST,
    HARVEST,
    MOVEMENT_ACTION_TYPES,
    NORTH,
    PLANT,
    SELL,
    SOUTH,
    WATER,
    Action,
)
from dimitri.planner.plan import Plan
from dimitri.planner.plan_evaluator import PlanEvaluator
from dimitri.planner.plan_generator import PlanGenerator, WheatPlanGenerator
from dimitri.planner.planner import Planner
from dimitri.planner.simulator import Simulator
from dimitri.planner.turn import Turn

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"
SPAWN = (4, 4)
WHEAT = Opportunity(OpportunityKind.WHEAT_PRODUCTION)
WEED = {"kind": "WEED"}


def _observation(*, step=0, money=None, farmer=SPAWN, tiles=None, shed=None):
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)
    observation["step"] = step
    observation["day"], observation["hour"] = divmod(step, 24)
    farm = observation["farms"][observation["player"]]
    if money is not None:
        farm["money"] = money
    farm["farmer"] = list(farmer)
    for (x, y), tile in (tiles or {}).items():
        farm["tiles"][y][x] = copy.deepcopy(tile)
    if shed is not None:
        observation["private"]["shed"] = shed
    return observation


def _state(**kwargs):
    return parse(_observation(**kwargs))


def _generate(state, opportunity=WHEAT):
    return WheatPlanGenerator().generate(state, opportunity)


def _only_plan(state):
    (plan,) = _generate(state)
    return plan


def _action_types(plan):
    return [a.action_type for a in plan.actions()]


def _steps_of(plan, action_type, start_step=0):
    """Return the game steps at which the plan's farmer or market performs ``action_type``."""
    return [
        start_step + i
        for i, turn in enumerate(plan.turns)
        if any(a.action_type == action_type for a in turn.actions())
    ]


def _occupied_nw_except(*free):
    """Tiles filling every NW-quadrant tile with a weed except ``free``."""
    return {(x, y): WEED for x in range(5) for y in range(5) if (x, y) not in free}


# --- the PlanGenerator boundary -----------------------------------------


def test_wheat_generator_is_a_plan_generator_for_wheat():
    generator = WheatPlanGenerator()

    assert isinstance(generator, PlanGenerator)
    assert generator.opportunity_kind is OpportunityKind.WHEAT_PRODUCTION


def test_plan_generator_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        PlanGenerator()


@pytest.mark.parametrize(
    "kind", [k for k in OpportunityKind if k is not OpportunityKind.WHEAT_PRODUCTION]
)
def test_unrelated_opportunities_produce_no_wheat_plan(kind):
    assert _generate(_state(), Opportunity(kind)) == ()


# --- a valid starting state ---------------------------------------------


def test_wheat_produces_one_plan_from_the_start_of_the_game():
    plan = _only_plan(_state())

    assert isinstance(plan, Plan)
    assert plan.opportunity == WHEAT
    assert plan.horizon == len(plan.turns)
    assert plan.label == "WHEAT at (4, 4)"


def test_plan_contains_every_step_in_order():
    plan = _only_plan(_state())

    assert plan.actions() == (
        Action(BUY_SEED, "WHEAT", 1),
        Action(PLANT, "WHEAT"),
        Action(WATER),
        Action(WATER),
        Action(WATER),
        Action(HARVEST),
        Action(DROP),
        Action(SELL, "WHEAT", 2),
    )


def test_plan_timing_follows_the_game_rules():
    plan = _only_plan(_state())

    # Planted and watered on day 0, watered on days 1 and 2 (age 2 is the
    # first harvestable day and inside the watering window), then harvested.
    assert _steps_of(plan, PLANT) == [1]
    assert _steps_of(plan, WATER) == [2, 24, 48]
    assert _steps_of(plan, HARVEST) == [49]
    # The drop is applied before the market, so the sale shares its turn.
    assert _steps_of(plan, DROP) == [50]
    assert _steps_of(plan, SELL) == [50]


def test_plan_represents_waiting_as_idle_turns():
    plan = _only_plan(_state())

    idle = [i for i, turn in enumerate(plan.turns) if turn == Turn()]
    assert idle == [*range(3, 24), *range(25, 48)]


def test_every_turn_uses_only_the_farmer_and_market():
    for turn in _only_plan(_state()).turns:
        assert turn.hands == ()


# --- movement ------------------------------------------------------------


def test_plot_away_from_spawn_needs_daily_walks():
    # Spawn is occupied, so the plot is the nearest empty tile: (4, 3).
    state = _state(tiles={SPAWN: WEED})

    plan = _only_plan(state)

    assert plan.label == "WHEAT at (4, 3)"
    moves = [a for a in plan.actions() if a.action_type in MOVEMENT_ACTION_TYPES]
    # North to the plot on day 0 and on each watering day, south back to drop.
    assert moves == [Action(NORTH)] * 3 + [Action(SOUTH)]


def test_farmer_away_from_the_plot_walks_there_first():
    state = _state(farmer=(0, 0))

    plan = _only_plan(state)

    # The seed is bought while the farmer takes its first step.
    assert plan.turns[0] == Turn(farmer=Action(EAST), market=(Action(BUY_SEED, "WHEAT", 1),))
    assert plan.turns[1:8] == tuple(
        [Turn(farmer=Action(EAST))] * 3 + [Turn(farmer=Action(SOUTH))] * 4
    )
    assert _steps_of(plan, PLANT) == [8]


def test_walks_are_straight_lines_east_west_first():
    state = _state(tiles=_occupied_nw_except((0, 0)))

    plan = _only_plan(state)

    first_day = [t.farmer.action_type for t in plan.turns[0:8]]
    assert first_day == ["WEST"] * 4 + ["NORTH"] * 4


def test_plot_is_the_empty_tile_nearest_spawn():
    state = _state(tiles={SPAWN: WEED, (4, 3): WEED})

    # (3, 4) and (4, 3) are both one step from spawn; ties go to the lower row.
    assert _only_plan(_state(tiles={SPAWN: WEED})).label == "WHEAT at (4, 3)"
    assert _only_plan(state).label == "WHEAT at (3, 4)"


# --- timing constraints --------------------------------------------------


def test_planting_waits_for_an_hour_that_allows_same_day_watering():
    # Starting at hour 22: the seed is bought at hour 22, and planting at
    # hour 23 would leave no turn to water, so the plant waits for day 1.
    plan = _only_plan(_state(step=22))

    assert _steps_of(plan, PLANT, start_step=22) == [24]
    assert _steps_of(plan, WATER, start_step=22)[0] == 25


def test_plan_starting_mid_game_uses_its_start_day():
    plan = _only_plan(_state(step=24 * 10 + 5))

    assert _steps_of(plan, HARVEST, start_step=24 * 10 + 5)[0] // 24 == 12


def test_no_plan_when_it_would_run_past_the_season():
    assert _generate(_state(step=24 * 28)) == ()


def test_plan_fits_just_before_the_season_ends():
    # Starting on day 27 the harvest is on day 29 and the sale fits by step 718.
    plan = _only_plan(_state(step=24 * 27))

    assert 24 * 27 + len(plan.turns) - 1 <= 718


# --- no plan when the state does not allow one ---------------------------


def test_insufficient_money_produces_no_plan():
    assert _generate(_state(money=9)) == ()


def test_exactly_enough_money_produces_a_plan():
    assert len(_generate(_state(money=10))) == 1


def test_no_empty_tile_produces_no_plan():
    assert _generate(_state(tiles=_occupied_nw_except())) == ()


def test_full_shed_that_cannot_take_the_harvest_produces_no_plan():
    # The harvest is discarded on DROP, so the SELL could not be simulated.
    assert _generate(_state(shed={"EGG": 100})) == ()


# --- plan validity and completion ---------------------------------------


@pytest.mark.parametrize(
    "state_kwargs",
    [{}, {"tiles": {SPAWN: WEED}}, {"farmer": (0, 0)}, {"step": 22}, {"step": 24 * 5 + 17}],
)
def test_generated_plan_can_be_simulated(state_kwargs):
    state = _state(**state_kwargs)

    plan = _only_plan(state)

    Simulator().simulate_plan(state, plan)


def test_generation_does_not_mutate_the_state():
    state = _state(farmer=(1, 1))
    before = copy.deepcopy(state)

    _generate(state)

    assert state == before


def test_generation_is_deterministic():
    assert _generate(_state()) == _generate(_state())


def test_plan_ends_with_the_harvest_sold():
    # Goods other than wheat are not WHEAT_PRODUCTION's to sell. (Wheat
    # already in the shed is sold: see test_wheat_continuation.py.)
    state = _state(shed={"EGG": 3})

    final = Simulator().simulate_plan(state, _only_plan(state))

    assert final.player.inventory.items["EGG"] == 3
    assert final.player.inventory.items.get("WHEAT", 0) == 0
    assert all(not inv.items for inv in final.player.unit_inventories)
    assert final.player.seeds["WHEAT"] == state.player.seeds["WHEAT"]
    assert final.player.farm.tiles[4][4] is None


def test_plan_sells_exactly_the_harvested_units():
    state = _state()
    plan = _only_plan(state)
    harvest_step = _steps_of(plan, HARVEST)[0]

    before_harvest = Simulator().simulate_plan(
        state, Plan(WHEAT, turns=plan.turns[:harvest_step], horizon=harvest_step)
    )
    plant = before_harvest.player.farm.tiles[4][4]

    assert isinstance(plant, PlantTile)
    assert plan.turns[-1].market == (Action(SELL, "WHEAT", plant.yield_units),)


# --- architecture: generation only --------------------------------------


def test_generator_does_not_evaluate_plans(monkeypatch):
    def _refuse(*args, **kwargs):
        raise AssertionError("plan generation must not evaluate plans")

    monkeypatch.setattr(PlanEvaluator, "evaluate_plan", _refuse)

    assert len(_generate(_state())) == 1


def test_plan_carries_no_score():
    plan = _only_plan(_state())

    assert not any(hasattr(plan, name) for name in ("score", "expected_profit", "roi", "risk"))


def test_planner_and_pipeline_do_not_generate_plans(monkeypatch):
    def _refuse(*args, **kwargs):
        raise AssertionError("the live pipeline must not generate plans")

    monkeypatch.setattr(WheatPlanGenerator, "generate", _refuse)
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)

    assert Pipeline().run(observation) == {"farmer": ["PASS"], "hands": [], "market": []}
    assert Planner().plan(parse(observation)).candidates[-1].turn == Turn()


# --- the real environment ------------------------------------------------


def _play_generated_plan(prefix):
    """Play ``prefix`` turns, then generate a wheat plan from the live observation and play it.

    Returns the observations, the generated plan, and the step it started at.
    """
    kaggle_environments = pytest.importorskip("kaggle_environments")
    received = {}
    operator = Operator()
    generated = {}

    def agent(obs):
        step = obs["step"]
        received[step] = copy.deepcopy(dict(obs))
        if step < len(prefix):
            return operator.execute(Decision(turn=prefix[step]))
        if "plan" not in generated:
            (generated["plan"],) = WheatPlanGenerator().generate(parse(received[step]), WHEAT)
        offset = step - len(prefix)
        turns = generated["plan"].turns
        return operator.execute(Decision(turn=turns[offset] if offset < len(turns) else Turn()))

    env = kaggle_environments.make(
        "kaggriculture",
        configuration={
            "episodeSteps": len(prefix) + 80,
            "weedSpawnChance": 0,
            "townShopUnlockInterval": 10_000,
            "seed": 19,
        },
        debug=True,
    )
    env.run([agent, "pass"])
    return received, generated["plan"], len(prefix)


def _assert_matches_environment(prefix):
    received, plan, start_step = _play_generated_plan(prefix)
    start = parse(received[start_step])
    end = parse(received[start_step + len(plan.turns)])

    predicted = Simulator().simulate_plan(start, plan)

    assert (predicted.step, predicted.day, predicted.hour) == (end.step, end.day, end.hour)
    assert predicted.player == end.player
    assert predicted.opponent == end.opponent
    assert predicted.market == end.market
    assert predicted.town == end.town
    return start, end, plan


def test_real_environment_wheat_plan_from_game_start():
    start, end, plan = _assert_matches_environment(prefix=[])

    assert plan.label == "WHEAT at (4, 4)"
    assert end.player.money > start.player.money
    assert end.player.inventory.items["WHEAT"] == 0


def test_real_environment_wheat_plan_with_walking():
    # Occupy the spawn tile with carrot and move the farmer off it, so the
    # generated plan must walk to its plot and back to the shed each day.
    prefix = [
        Turn(market=(Action(BUY_SEED, "CARROT", 1),)),
        Turn(farmer=Action(PLANT, "CARROT")),
        Turn(farmer=Action(WATER)),
        Turn(farmer=Action("WEST")),
        Turn(farmer=Action(NORTH)),
    ]

    start, end, plan = _assert_matches_environment(prefix)

    assert tuple(start.player.farm.farmer) == (3, 3)
    assert plan.label == "WHEAT at (4, 3)"
    assert any(a.action_type in MOVEMENT_ACTION_TYPES for a in plan.actions())
    assert end.player.inventory.items["WHEAT"] == 0
