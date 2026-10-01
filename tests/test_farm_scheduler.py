"""Tests for the FarmScheduler and the plans built on it.

A PlanGenerator decides which economic hypothesis to test; the
FarmScheduler realizes it as turns while keeping every maintainable
WHEAT and TOMATO plant on the farm alive and selling its output. Jobs
are derived purely from the GameState each turn and served survival
first, then value at risk, then construction, then routine work, the
nearest first within a priority.

These tests cover job derivation, ordering, timing boundaries, the
tomato capacity wave, cross-crop preservation, market-order packing,
and agreement with the real environment.
"""

import copy
import json
from pathlib import Path

import pytest

from dimitri.analyst.opportunity import Opportunity, OpportunityKind
from dimitri.executive.decision import Decision
from dimitri.models.tile import PlantTile, WeedTile
from dimitri.observer.parser import parse
from dimitri.operator.operator import Operator
from dimitri.planner.action import (
    BUY_SEED,
    DROP,
    EAST,
    HARVEST,
    NORTH,
    PLANT,
    SELL,
    SOUTH,
    WATER,
    WEST,
    Action,
)
from dimitri.planner.farm_scheduler import (
    ROUTINE,
    SURVIVAL,
    VALUE,
    FarmScheduler,
    Hypothesis,
    Job,
    care_jobs,
    planting_order,
    plant_jobs,
    tour_cost,
)
from dimitri.planner.plan_generator import TomatoPlanGenerator, WheatPlanGenerator, tomato_program_limit
from dimitri.planner.simulator import Simulator
from dimitri.planner.turn import Turn
from dimitri.utils.constants import LAST_ACTION_STEP

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"
SPAWN = (4, 4)
WHEAT = Opportunity(OpportunityKind.WHEAT_PRODUCTION)
TOMATO = Opportunity(OpportunityKind.TOMATO_PRODUCTION)
WEED = {"kind": "WEED"}


def _plant(crop, planted_day, *, watered=False, unwatered=0, yield_units=None, final=False):
    if yield_units is None:
        yield_units = 1 if crop == "WHEAT" else 0
    if crop == "WHEAT":
        lifespan = (planted_day + 5) * 24
    else:
        lifespan = (planted_day + 12) * 24 if final else -1
    return {
        "kind": "PLANT",
        "crop": crop,
        "planted_day": planted_day,
        "watered_today": watered,
        "consecutive_unwatered": unwatered,
        "yield_units": yield_units,
        "max_lifespan_step": lifespan,
        "fertilized_until_day": -1,
    }


def _state(*, step=0, money=None, farmer=SPAWN, tiles=None, seeds=None, carried=None, shed=None):
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
    private = observation["private"]
    private["seeds"].update(seeds or {})
    private["shed"].update(shed or {})
    if carried is not None:
        private["inventories"] = [dict(carried)]
    return parse(observation)


NW = planting_order(_state())
"""The NW tiles in planting order: nearest the spawn tile first, then row, then column."""


def _generated(generator, state, opportunity):
    (generated,) = generator.generate_with_states(state, opportunity)
    return generated


def _tomato_plan(state):
    return _generated(TomatoPlanGenerator(), state, TOMATO)


def _wheat_plan(state):
    return _generated(WheatPlanGenerator(), state, WHEAT)


def _farmer_actions(plan):
    return [t.farmer for t in plan.turns]


def _steps_of(plan, action_type, start_step=0):
    return [
        start_step + i
        for i, turn in enumerate(plan.turns)
        if any(a.action_type == action_type for a in turn.actions())
    ]


def _sold(plan, crop):
    return sum(a.quantity for a in plan.actions() if a.action_type == SELL and a.target == crop)


def _tile(state, xy):
    x, y = xy
    return state.player.farm.tiles[y][x]


def _alive(state, xy):
    return isinstance(_tile(state, xy), PlantTile)


# --- job derivation -----------------------------------------------------


@pytest.mark.parametrize(
    ("tile", "step", "expected"),
    [
        (_plant("WHEAT", 0, unwatered=1), 5, [Job(SURVIVAL, SPAWN, WATER)]),
        (_plant("WHEAT", 0), 30, [Job(ROUTINE, SPAWN, WATER)]),
        (_plant("WHEAT", 0, watered=True), 30, []),
        # Age 2: water first while it adds yield, then harvest.
        (_plant("WHEAT", 0), 48, [Job(ROUTINE, SPAWN, WATER)]),
        (_plant("WHEAT", 0, watered=True, yield_units=2), 49, [Job(ROUTINE, SPAWN, HARVEST)]),
        # Decaying wheat: harvest is urgent, and water no longer helps.
        (_plant("WHEAT", 0, yield_units=3), 121, [Job(VALUE, SPAWN, HARVEST)]),
        (_plant("TOMATO", 0, unwatered=1), 5, [Job(SURVIVAL, SPAWN, WATER)]),
        (_plant("TOMATO", 0, yield_units=2), 24 * 9, [Job(ROUTINE, SPAWN, WATER)]),
        (_plant("TOMATO", 0, yield_units=4), 24 * 9, [Job(VALUE, SPAWN, HARVEST)]),
        (_plant("TOMATO", 0, yield_units=4, final=True), 24 * 11, [Job(VALUE, SPAWN, HARVEST)]),
        # Spent: harvested, nothing left to produce.
        (_plant("TOMATO", 0, final=True), 24 * 11 + 3, []),
        # Planted too late for any production refreshed in season.
        (_plant("TOMATO", 22), 24 * 25, []),
    ],
    ids=[
        "wheat dies tonight", "wheat routine water", "wheat watered", "wheat water before harvest",
        "wheat harvest", "wheat decaying", "tomato dies tonight", "tomato routine water",
        "tomato at its cap", "tomato harvest day", "tomato spent", "tomato too late",
    ],
)
def test_jobs_are_derived_from_the_plant_and_the_clock(tile, step, expected):
    state = _state(step=step, tiles={SPAWN: tile})

    assert plant_jobs(state, SPAWN, _tile(state, SPAWN)) == expected
    assert care_jobs(state) == expected


def test_jobs_depend_only_on_the_state():
    state = _state(step=30, tiles={SPAWN: _plant("WHEAT", 0), (0, 0): _plant("TOMATO", 1, unwatered=1)})

    assert care_jobs(state) == care_jobs(copy.deepcopy(state))


def test_unreachable_survival_job_is_left_out():
    # Hour 23: the plant at (0, 0) is eight steps away and dies tonight anyway.
    state = _state(step=23, tiles={(0, 0): _plant("TOMATO", 0, unwatered=1)})

    assert care_jobs(state) == []


def test_tour_cost_counts_steps_and_one_action_per_tile():
    assert tour_cost(SPAWN, []) == 0
    assert tour_cost(SPAWN, [SPAWN]) == 1
    assert tour_cost(SPAWN, [(4, 3), (0, 0)]) == 1 + 1 + 7 + 1


# --- ordering -----------------------------------------------------------


def test_survival_is_served_before_a_nearer_routine_job():
    state = _state(step=30, tiles={(4, 3): _plant("TOMATO", 1), (0, 4): _plant("TOMATO", 0, unwatered=1)})

    plan = _tomato_plan(state).plan

    # (4, 3) is one step away but can wait; (0, 4) dies tonight.
    assert _farmer_actions(plan)[:5] == [Action(WEST)] * 4 + [Action(WATER)]


def test_harvest_at_risk_is_served_before_routine_care():
    state = _state(
        step=24 * 9 + 1,
        tiles={(4, 3): _plant("TOMATO", 1), (3, 3): _plant("TOMATO", 0, yield_units=4)},
    )

    plan = _tomato_plan(state).plan

    # The full plant at (3, 3) would waste tonight's production.
    assert _farmer_actions(plan)[:3] == [Action(WEST), Action(NORTH), Action(HARVEST)]


def test_equally_urgent_jobs_are_done_nearest_then_by_row_then_column():
    tiles = {(3, 4): _plant("TOMATO", 0), (4, 3): _plant("TOMATO", 0), (4, 2): _plant("TOMATO", 0)}

    plan = _tomato_plan(_state(step=24 + 2, tiles=tiles)).plan

    assert _farmer_actions(plan)[:7] == [
        Action(NORTH), Action(WATER),  # (4, 3): one step, lower row than (3, 4)
        Action(NORTH), Action(WATER),  # (4, 2): now the nearest
        Action(WEST), Action(SOUTH), Action(SOUTH),
    ]


def test_care_starts_from_the_farmers_current_position():
    state = _state(step=30, farmer=(0, 0), tiles={(2, 3): _plant("TOMATO", 0, unwatered=1)})

    plan = _tomato_plan(state).plan

    assert _farmer_actions(plan)[:6] == [Action(EAST)] * 2 + [Action(SOUTH)] * 3 + [Action(WATER)]


# --- timing boundaries --------------------------------------------------


def test_every_new_plant_is_watered_on_its_planting_turn_plus_one():
    plan = _tomato_plan(_state()).plan

    for step in _steps_of(plan, PLANT):
        assert plan.turns[step + 1].farmer == Action(WATER)
        assert (step + 1) // 24 == step // 24


def test_planting_may_use_hour_22_but_not_hour_23():
    at_22 = _wheat_plan(_state(step=22, seeds={"WHEAT": 1})).plan
    at_23 = _wheat_plan(_state(step=23, seeds={"WHEAT": 1})).plan

    assert _steps_of(at_22, PLANT, 22) == [22] and _steps_of(at_22, WATER, 22)[0] == 23
    assert _steps_of(at_23, PLANT, 23) == [24]


def test_program_planting_spreads_across_days_and_runs():
    # A first run while care capacity lasts, then a second once the first
    # run's harvest frees it.
    plan = _tomato_plan(_state()).plan

    days = sorted({step // 24 for step in _steps_of(plan, PLANT)})

    assert len(_steps_of(plan, PLANT)) == 21
    assert days == [0, 1, 2, 12, 13, 14, 15]


def test_harvest_comes_before_decay():
    # Decay starts at step 288: the plant is harvested on its last day.
    state = _state(step=24 * 11 + 3, farmer=(0, 0), tiles={(4, 3): _plant("TOMATO", 0, yield_units=4, final=True)})

    plan = _tomato_plan(state).plan

    (harvest,) = _steps_of(plan, HARVEST, state.step)
    assert harvest < 288
    assert _sold(plan, "TOMATO") == 4


def test_the_night_returns_the_farmer_and_drops_its_load():
    # Walking back at hour 23, the night does the walking and the drop.
    state = _state(step=23, farmer=(0, 0), carried={"TOMATO": 3})

    plan = _tomato_plan(state).plan

    assert plan.turns == (Turn(farmer=Action(EAST)), Turn(market=(Action(SELL, "TOMATO", 3),)))


def test_the_final_sale_takes_precedence_on_the_last_action_step():
    # A harvest now could no longer be sold; the carried wheat still can.
    state = _state(step=LAST_ACTION_STEP, tiles={SPAWN: _plant("WHEAT", 27, watered=True, yield_units=2)}, carried={"WHEAT": 3})

    plan = _wheat_plan(state).plan

    assert plan.turns == (Turn(farmer=Action(DROP), market=(Action(SELL, "WHEAT", 3),)),)


# --- capacity and rejection ---------------------------------------------


def test_obligations_beyond_a_days_capacity_reject_every_hypothesis():
    # Twenty tomatoes that die tonight cannot all be watered in 19 turns.
    state = _state(step=5, tiles={t: _plant("TOMATO", 0, unwatered=1) for t in NW[:20]})

    assert TomatoPlanGenerator().generate(state, TOMATO) == ()
    assert WheatPlanGenerator().generate(state, WHEAT) == ()


def test_scheduler_rejects_a_hypothesis_that_would_lose_a_plant():
    state = _state(step=5, tiles={t: _plant("TOMATO", 0, unwatered=1) for t in NW[:20]})

    assert FarmScheduler().schedule(state, Hypothesis()) is None


def test_plants_that_cannot_be_reached_in_time_do_not_block_a_hypothesis():
    state = _state(step=23, tiles={(0, 0): _plant("WHEAT", 0, unwatered=1)}, seeds={"WHEAT": 1})

    generated = _wheat_plan(state)

    assert generated.plan.label == "WHEAT at (4, 4)"
    assert isinstance(_tile(generated.resulting_state, (0, 0)), WeedTile)


# --- the capacity wave --------------------------------------------------


def test_largest_feasible_program_from_the_starting_state():
    # Up to 25 tomatoes could be requested; 21 is the largest the
    # scheduler can plant and sell, in two planting runs.
    state = _state()
    generated = _tomato_plan(state)
    plan = generated.plan

    assert tomato_program_limit(state) == 25
    assert plan.label == "TOMATO wave of 21"
    assert plan.turns[0].market == (Action(BUY_SEED, "TOMATO", 21),)
    assert _sold(plan, "TOMATO") == 84
    assert generated.resulting_state.player.money > state.player.money
    assert generated.resulting_state.player.inventory.items["TOMATO"] == 0
    assert all(not inv.items for inv in generated.resulting_state.player.unit_inventories)


def test_program_is_deterministic():
    assert _tomato_plan(_state()) == _tomato_plan(_state())


@pytest.mark.parametrize(
    ("kwargs", "k"),
    [
        ({"money": 199}, 3),
        ({"tiles": {t: WEED for t in NW[4:]}}, 4),
        # Daily care capacity no longer limits the request: only empty tiles do.
        ({"step": 2, "tiles": {t: _plant("TOMATO", 0, watered=True) for t in NW[:6]}}, 19),
    ],
    ids=["money", "tiles", "existing plants take tiles"],
)
def test_program_request_is_limited_by_money_and_tiles(kwargs, k):
    assert tomato_program_limit(_state(**kwargs)) == k


def test_wave_is_reduced_until_it_fits_the_remaining_season():
    # Day 21, hour 10: tomatoes planted on day 22 could produce nothing.
    state = _state(step=24 * 21 + 10)
    plan = _tomato_plan(state).plan

    planted = len(_steps_of(plan, PLANT))
    assert 1 < planted < tomato_program_limit(state)
    assert all(step // 24 == 21 for step in _steps_of(plan, PLANT, state.step))
    assert _sold(plan, "TOMATO") == planted


def test_wave_never_loses_a_planted_tomato():
    generated = _tomato_plan(_state())

    # Every planted tomato produced four units, all sold: none died.
    assert _sold(generated.plan, "TOMATO") == 4 * len(_steps_of(generated.plan, PLANT))


def test_one_tomato_hypothesis_per_state():
    generator = TomatoPlanGenerator()
    for state in (_state(), _state(money=199), _state(step=24 * 21 + 10), _state(seeds={"TOMATO": 3})):
        assert len(generator.generate(state, TOMATO)) == 1


# --- cross-crop preservation --------------------------------------------


def test_a_tomato_wave_keeps_existing_wheat_alive_and_sells_it():
    state = _state(step=0, tiles={(0, 0): _plant("WHEAT", 0, unwatered=1)})

    generated = _tomato_plan(state)

    assert _tile(generated.resulting_state, (0, 0)) is None  # harvested, not a weed
    assert _sold(generated.plan, "WHEAT") > 0


def test_a_wheat_plan_keeps_an_existing_tomato_alive():
    state = _state(step=24 * 3 + 2, tiles={(0, 0): _plant("TOMATO", 1, unwatered=1)})

    generated = _wheat_plan(state)
    tomato = _tile(generated.resulting_state, (0, 0))

    assert generated.plan.label == "WHEAT at (4, 4)"
    assert isinstance(tomato, PlantTile) and tomato.crop == "TOMATO"
    assert tomato.consecutive_unwatered == 0


def test_existing_wheat_and_tomato_both_receive_care():
    state = _state(step=24 + 2, tiles={(4, 3): _plant("WHEAT", 1, unwatered=1), (3, 4): _plant("TOMATO", 1, unwatered=1)})

    plan = _wheat_plan(state).plan

    assert _farmer_actions(plan)[:5] == [Action(NORTH), Action(WATER), Action(WEST), Action(SOUTH), Action(WATER)]


def _harvest_steps_on(state, plan, tile):
    """The steps at which the farmer harvests standing on ``tile``."""
    steps, current = [], state
    for turn in plan.turns:
        if turn.farmer == Action(HARVEST) and tuple(current.player.farm.farmer) == tile:
            steps.append(current.step)
        current = Simulator().play_turn(current, turn, isolated=False)
    return steps


def test_wheat_harvest_due_during_program_construction_is_harvested():
    # Planting outranks a routine harvest, so with a large program to plant
    # the wheat waits, but it is harvested before it starts to decay (step
    # 120) and sold.
    state = _state(step=48, tiles={(0, 0): _plant("WHEAT", 0, watered=False)})

    generated = _tomato_plan(state)

    (harvest,) = _harvest_steps_on(state, generated.plan, (0, 0))
    assert harvest < 120
    assert _tile(generated.resulting_state, (0, 0)) is None
    assert _sold(generated.plan, "WHEAT") > 0


def test_tomato_about_to_decay_is_harvested_during_a_wheat_plan():
    state = _state(step=24 * 11 + 4, tiles={(0, 0): _plant("TOMATO", 0, yield_units=4, final=True)})

    generated = _wheat_plan(state)

    assert generated.plan.label == "WHEAT at (4, 4)"
    assert _sold(generated.plan, "TOMATO") == 4


def test_a_program_is_reduced_rather_than_lose_existing_plants():
    # Six tomatoes already need daily care and 19 seeds are held: the
    # program plants only as many as it can without losing any of them.
    existing = {t: _plant("TOMATO", 0, watered=True) for t in NW[:6]}
    state = _state(step=2, tiles=existing, seeds={"TOMATO": 19})

    generated = _generated(TomatoPlanGenerator(), state, TOMATO)

    planted = len(_steps_of(generated.plan, PLANT))
    assert 0 < planted < 19
    # Each existing tomato is harvested (none was lost before its harvest
    # day); spent, they may decay to weeds afterwards.
    assert all(_harvest_steps_on(state, generated.plan, t) for t in existing)


# --- market-order packing -----------------------------------------------


def test_drop_and_sell_share_the_final_turn():
    plan = _wheat_plan(_state()).plan

    assert plan.turns[-1] == Turn(farmer=Action(DROP), market=(Action(SELL, "WHEAT", 2),))


def test_seed_purchase_shares_a_turn_with_movement():
    plan = _wheat_plan(_state(tiles={SPAWN: WEED})).plan

    assert plan.turns[0] == Turn(farmer=Action(NORTH), market=(Action(BUY_SEED, "WHEAT", 1),))


def test_seed_purchase_shares_a_turn_with_care():
    state = _state(step=2, tiles={SPAWN: _plant("WHEAT", 0, unwatered=1)})

    plan = _tomato_plan(state).plan

    assert plan.turns[0].farmer == Action(WATER)
    assert plan.turns[0].market[0].action_type == BUY_SEED


@pytest.mark.parametrize(
    "state",
    [_state(), _state(tiles={SPAWN: WEED}), _state(farmer=(0, 0)), _state(step=22)],
    ids=["spawn plot", "plot away", "farmer away", "late hour"],
)
def test_a_seed_bought_in_a_turn_is_never_planted_in_that_turn(state):
    for generated in (
        WheatPlanGenerator().generate_with_states(state, WHEAT)
        + TomatoPlanGenerator().generate_with_states(state, TOMATO)
    ):
        for turn in generated.plan.turns:
            bought = {a.target for a in turn.market if a.action_type == BUY_SEED}
            assert not (turn.farmer and turn.farmer.action_type == PLANT and turn.farmer.target in bought)


def test_packed_turns_simulate_to_the_generated_state():
    for state in (_state(), _state(step=2, tiles={SPAWN: _plant("WHEAT", 0, unwatered=1)})):
        for generated in (_wheat_plan(state), _tomato_plan(state)):
            assert Simulator().simulate_plan(state, generated.plan) == generated.resulting_state


# --- the real environment -----------------------------------------------


def _replan_in_environment(prefix, generator, opportunity):
    """Play ``prefix``, generate one plan from the live observation, play it, and compare."""
    kaggle_environments = pytest.importorskip("kaggle_environments")
    received, run = {}, {}
    operator = Operator()

    def agent(obs):
        step = obs["step"]
        received[step] = copy.deepcopy(dict(obs))
        if step < len(prefix):
            return operator.execute(Decision(turn=prefix[step]))
        if step == len(prefix):
            (run["generated"],) = generator.generate_with_states(parse(received[step]), opportunity)
        turns = run["generated"].plan.turns
        offset = step - len(prefix)
        return operator.execute(Decision(turn=turns[offset] if offset < len(turns) else Turn()))

    env = kaggle_environments.make(
        "kaggriculture",
        configuration={"episodeSteps": LAST_ACTION_STEP + 2, "weedSpawnChance": 0, "townShopUnlockInterval": 10_000, "seed": 37},
        debug=True,
    )
    env.run([agent, "pass"])
    final = env.steps[-1][0].observation
    received.setdefault(final["step"], copy.deepcopy(dict(final)))
    generated = run["generated"]
    start = parse(received[len(prefix)])
    end = parse(received[len(prefix) + len(generated.plan.turns)])
    predicted = generated.resulting_state
    assert (predicted.step, predicted.day, predicted.hour) == (end.step, end.day, end.hour)
    assert predicted.player == end.player
    assert predicted.opponent == end.opponent
    assert predicted.market == end.market
    return start, generated, end


def _plant_tomatoes_at(*tiles):
    """Buy tomato seeds, then walk to, plant and water each tile on day 0."""
    turns = [Turn(market=(Action(BUY_SEED, "TOMATO", len(tiles)),))]
    position = SPAWN
    for x, y in tiles:
        while position != (x, y):
            px, py = position
            if px != x:
                step, position = (Action(EAST), (px + 1, py)) if x > px else (Action(WEST), (px - 1, py))
            else:
                step, position = (Action(SOUTH), (px, py + 1)) if y > py else (Action(NORTH), (px, py - 1))
            turns.append(Turn(farmer=step))
        turns += [Turn(farmer=Action(PLANT, "TOMATO")), Turn(farmer=Action(WATER))]
    return turns


@pytest.mark.parametrize(
    "tiles", [((4, 4), (4, 3)), ((4, 4), (0, 0))], ids=["adjacent tomatoes", "distant tomatoes"]
)
def test_real_environment_two_tomatoes_are_continued(tiles):
    start, generated, end = _replan_in_environment(_plant_tomatoes_at(*tiles), TomatoPlanGenerator(), TOMATO)

    assert generated.plan.label == "continue TOMATO wave of 2"
    assert _sold(generated.plan, "TOMATO") == 8


def test_real_environment_wave_with_existing_wheat():
    prefix = [Turn(market=(Action(BUY_SEED, "WHEAT", 1),)), Turn(farmer=Action(PLANT, "WHEAT")), Turn(farmer=Action(WATER))]

    start, generated, end = _replan_in_environment(prefix, TomatoPlanGenerator(), TOMATO)

    assert generated.plan.label.startswith("TOMATO wave of ")
    assert _sold(generated.plan, "WHEAT") > 0


def test_real_environment_conflicting_obligations():
    # Day 2: a wheat harvest is due at spawn and two tomatoes need water,
    # while a wheat plan wants to plant. The wheat goes to the nearest free tile.
    prefix = (
        [Turn(market=(Action(BUY_SEED, "WHEAT", 1),)), Turn(farmer=Action(PLANT, "WHEAT")), Turn(farmer=Action(WATER))]
        + _plant_tomatoes_at((0, 0), (0, 4))
    )
    prefix += [Turn()] * (24 - len(prefix))
    prefix += [Turn(farmer=Action(WATER))] + [Turn()] * 23  # day 1: water the wheat only

    start, generated, end = _replan_in_environment(prefix, WheatPlanGenerator(), WHEAT)

    assert start.day == 2
    for tile in ((0, 0), (0, 4)):
        assert isinstance(_tile(end, tile), PlantTile)
