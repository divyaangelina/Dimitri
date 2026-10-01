"""Differential tests: the #050 performance changes compute exactly the same results.

Each optimization is checked against a reference copy of the code it
replaced, kept here as a correctness oracle:

- farm_after_turn returns an unchanged farm without visiting its tiles
  when no tile can change (``changes_after_turn``);
- the Simulator keeps a Player or Opponent whose farm did not change;
- tomato_harvest_day is computed in closed form;
- the scheduler checks for lost plants only when the tile grid changed;
- the tomato wave search skips sizes above max_tomato_plantings, which
  the scheduler would reject anyway.

Results must match exactly: resulting states, accepted wave sizes,
plans, and continuation projections.
"""

import copy
import itertools
import json
from dataclasses import replace
from pathlib import Path

import pytest

from dimitri.analyst.opportunity import Opportunity, OpportunityKind
from dimitri.executive.decision import Decision
from dimitri.models.tile import PlantTile, WeedTile
from dimitri.observer.parser import parse
from dimitri.operator.operator import Operator
from dimitri.planner import farm_scheduler, plan_generator, simulator, time_rules
from dimitri.planner.action import BUY_SEED, PLANT, WATER, Action
from dimitri.planner.continuation import ContinuationEvaluator
from dimitri.planner.farm_scheduler import (
    MANAGED_CROPS,
    FarmScheduler,
    Hypothesis,
    has_value,
    max_tomato_plantings,
    planting_order,
    production_days,
    refreshed_in_season,
    tomato_harvest_day,
)
from dimitri.planner.plan_generator import TomatoPlanGenerator, WheatPlanGenerator, tomato_program_limit
from dimitri.planner.simulator import Simulator
from dimitri.planner.time_rules import changes_after_turn, farm_after_turn
from dimitri.planner.turn import Turn
from dimitri.utils.constants import LAST_ACTION_STEP, TURNS_PER_DAY

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"
SPAWN = (4, 4)
WHEAT = Opportunity(OpportunityKind.WHEAT_PRODUCTION)
TOMATO = Opportunity(OpportunityKind.TOMATO_PRODUCTION)
WEED = {"kind": "WEED"}


def _plant(crop, planted_day, *, watered=False, unwatered=0, yield_units=None, lifespan=None):
    if yield_units is None:
        yield_units = 1 if crop == "WHEAT" else 0
    if lifespan is None:
        lifespan = (planted_day + 5) * 24 if crop == "WHEAT" else -1
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


def _state(*, step=0, money=None, farmer=SPAWN, tiles=None, opponent_tiles=None, seeds=None):
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
    opponent = observation["farms"][1 - observation["player"]]
    for (x, y), tile in (opponent_tiles or {}).items():
        opponent["tiles"][y][x] = copy.deepcopy(tile)
    observation["private"]["seeds"].update(seeds or {})
    return parse(observation)


NW = planting_order(_state())


# --- reference copies of the code each optimization replaced ------------


def _reference_decayed_tile(tile, step):
    if not isinstance(tile, PlantTile):
        return tile
    lifespan = tile.max_lifespan_step
    if lifespan < 0 or step < lifespan or (step - lifespan) % 2 != 0:
        return tile
    yield_units = tile.yield_units - 1
    if yield_units <= 0:
        return WeedTile()
    return replace(tile, yield_units=yield_units)


def reference_farm_after_turn(farm, step):
    """farm_after_turn before #050: every tile rebuilt on every turn."""
    tiles = tuple(tuple(_reference_decayed_tile(tile, step) for tile in row) for row in farm.tiles)
    if not time_rules.is_last_turn_of_day(step):
        return replace(farm, tiles=tiles)
    day = step // TURNS_PER_DAY
    tiles = tuple(tuple(time_rules._tile_at_end_of_day(tile, day) for tile in row) for row in tiles)
    return replace(farm, tiles=tiles, farmer=time_rules.spawn_position(farm), hands=[], hires_today=0)


def reference_tomato_harvest_day(plant, tile, spawn):
    """tomato_harvest_day before #050: the useful production days, listed."""
    walk = abs(spawn[0] - tile[0]) + abs(spawn[1] - tile[1])
    useful = [
        day
        for day in production_days(plant)
        if refreshed_in_season(day)
        and (day + 1) * TURNS_PER_DAY + 2 * walk + 1 <= farm_scheduler.LAST_ACTION_STEP
    ]
    return useful[-1] + 1 if useful else None


def _reference_play(self, farmer, market):
    """_Run._play before #050: every tile checked for a lost plant after every turn."""
    before = self._state
    if before.step > LAST_ACTION_STEP:
        raise ValueError("Past the season's last action")
    turn = Turn(farmer=farmer, market=market)
    self._state = self._simulator.play_turn(before, turn, isolated=False)
    self._turns.append(turn)
    tiles_after = self._state.player.farm.tiles
    for y, row in enumerate(before.player.farm.tiles):
        for x, plant in enumerate(row):
            if (
                isinstance(plant, PlantTile)
                and plant.crop in MANAGED_CROPS
                and isinstance(tiles_after[y][x], WeedTile)
                and (x, y) not in self._exempt
                and has_value(plant, (x, y), before)
            ):
                raise ValueError(f"The {plant.crop} on {(x, y)} was lost")


@pytest.fixture
def reference(monkeypatch):
    """Switch every #050 optimization back to its reference implementation."""
    monkeypatch.setattr(simulator, "farm_after_turn", reference_farm_after_turn)
    monkeypatch.setattr(simulator, "_with_farm", lambda owner, farm: replace(owner, farm=farm))
    monkeypatch.setattr(farm_scheduler, "tomato_harvest_day", reference_tomato_harvest_day)
    monkeypatch.setattr(farm_scheduler._Run, "_play", _reference_play)
    monkeypatch.setattr(plan_generator, "max_tomato_plantings", lambda state: 10**9)


# --- farm_after_turn ----------------------------------------------------


FARMS = {
    "empty": {},
    "fresh wheat": {SPAWN: _plant("WHEAT", 3, unwatered=1)},
    "growing wheat": {SPAWN: _plant("WHEAT", 2, yield_units=2)},
    "wheat decaying": {SPAWN: _plant("WHEAT", 0, yield_units=3)},
    "wheat about to die": {SPAWN: _plant("WHEAT", 0, yield_units=1)},
    "fresh tomato": {SPAWN: _plant("TOMATO", 3, unwatered=1)},
    "tomato before production": {SPAWN: _plant("TOMATO", 0)},
    "tomato with yield": {SPAWN: _plant("TOMATO", 0, yield_units=2)},
    "tomato decaying": {SPAWN: _plant("TOMATO", 0, yield_units=4, lifespan=120)},
    "spent tomato": {SPAWN: _plant("TOMATO", 0, yield_units=0, lifespan=120)},
    "weeds": {SPAWN: WEED, (0, 0): WEED},
    "mixed crops": {
        SPAWN: _plant("WHEAT", 0, yield_units=2),
        (4, 3): _plant("TOMATO", 1, yield_units=4, lifespan=121),
        (0, 0): _plant("WHEAT", 1, yield_units=1),
        (2, 2): WEED,
    },
}
STEPS = [0, 5, 22, 23, 24, 119, 120, 121, 122, 123, 125, 143, 144, 696, 717, 718]


@pytest.mark.parametrize("farm_name", list(FARMS))
def test_farm_after_turn_matches_the_reference_on_both_farms(farm_name):
    tiles = FARMS[farm_name]
    state = _state(tiles=tiles, opponent_tiles=tiles)
    for farm in (state.player.farm, state.opponent.farm):
        # Parsed grids are lists; simulated ones are tuples. Try both.
        tuple_farm = replace(farm, tiles=tuple(tuple(row) for row in farm.tiles))
        for grid, step in itertools.product((farm, tuple_farm), STEPS):
            assert farm_after_turn(grid, step) == reference_farm_after_turn(grid, step), (farm_name, step)
            assert all(isinstance(row, tuple) for row in farm_after_turn(grid, step).tiles)


@pytest.mark.parametrize("farm_name", list(FARMS))
def test_no_change_is_reported_only_when_the_reference_changes_nothing(farm_name):
    farm = _state(tiles=FARMS[farm_name]).player.farm
    farm = replace(farm, tiles=tuple(tuple(row) for row in farm.tiles))
    for step in range(0, 250):
        if not changes_after_turn(farm, step):
            assert reference_farm_after_turn(farm, step) == farm, (farm_name, step)


def test_decay_boundary_steps_are_processed():
    # Lifespan 120: decay on 120, 122, ... and never on odd offsets.
    farm = _state(tiles={SPAWN: _plant("WHEAT", 0, yield_units=3)}).player.farm
    assert [step for step in range(116, 130) if changes_after_turn(farm, step)] == [119, 120, 122, 124, 126, 128]


def test_playing_turns_matches_the_reference_simulator():
    states = [
        _state(tiles=FARMS["mixed crops"], step=118),
        _state(tiles=FARMS["tomato decaying"], opponent_tiles=FARMS["wheat decaying"], step=110),
        _state(step=20),
    ]
    turns = [Turn(), Turn(farmer=Action(WATER)), Turn(farmer=Action("NORTH")), Turn()]
    for start in states:
        optimized = reference_state = start
        reference_sim = Simulator()
        for i in range(40):
            turn = turns[i % len(turns)]
            try:
                optimized = Simulator().play_turn(optimized, turn)
            except ValueError:
                turn = Turn()
                optimized = Simulator().play_turn(optimized, turn)
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(simulator, "farm_after_turn", reference_farm_after_turn)
                mp.setattr(simulator, "_with_farm", lambda owner, farm: replace(owner, farm=farm))
                reference_state = reference_sim.play_turn(reference_state, turn)
            assert optimized == reference_state


# --- tomato_harvest_day -------------------------------------------------


@pytest.mark.parametrize("last_action_step", [LAST_ACTION_STEP, 24 * 29 + 5, 24 * 20 + 7, 24 * 12])
def test_closed_form_harvest_day_matches_the_reference(last_action_step, monkeypatch):
    monkeypatch.setattr(farm_scheduler, "LAST_ACTION_STEP", last_action_step)
    for planted_day in range(0, 31):
        plant = PlantTile("TOMATO", planted_day, False, 0, 0, -1, -1)
        for tile in NW + [(9, 9)]:
            assert tomato_harvest_day(plant, tile, SPAWN) == reference_tomato_harvest_day(plant, tile, SPAWN)
    wheat = PlantTile("WHEAT", 0, False, 0, 1, 120, -1)
    assert tomato_harvest_day(wheat, SPAWN, SPAWN) is None


# --- the wave-size search -----------------------------------------------


WAVE_STATES = {
    **{f"day {d}": {"step": 24 * d} for d in (0, 5, 10, 15, 20, 24, 27, 28)},
    **{f"day {d} hour {h}": {"step": 24 * d + h} for d in (18, 19, 20, 21) for h in (3, 8, 11, 15, 21)},
    "existing wheat": {"step": 24 * 3 + 2, "tiles": {(0, 0): _plant("WHEAT", 3, unwatered=1)}},
    "existing tomato": {"step": 24 * 3 + 2, "tiles": {(0, 0): _plant("TOMATO", 2, unwatered=1)}},
    "both crops": {"step": 24 * 6, "tiles": {(0, 0): _plant("TOMATO", 1), (0, 4): _plant("WHEAT", 5)}},
    "held seeds": {"step": 24 * 19 + 4, "seeds": {"TOMATO": 9}},
    "limited money": {"step": 24 * 19, "money": 249},
    "limited tiles": {"step": 24 * 18, "tiles": {t: WEED for t in NW[3:]}},
    "deadline heavy": {"step": 24 * 18 + 6, "tiles": {t: _plant("TOMATO", 17, unwatered=1) for t in NW[:5]}},
    "nearly saturated": {"step": 24 * 2 + 2, "tiles": {t: _plant("TOMATO", 1) for t in NW[:9]}},
    "far plants day 18": {"step": 24 * 18 + 2, "tiles": {(0, 0): _plant("TOMATO", 18), (0, 4): _plant("WHEAT", 18)}},
}


def _tomato_plan(state):
    generated = TomatoPlanGenerator().generate_with_states(state, TOMATO)
    return generated[0] if generated else None


@pytest.mark.parametrize("name", list(WAVE_STATES))
def test_accepted_wave_size_matches_the_reference_search(name, request):
    # The reference is the pre-#050 search: decrement from the capacity
    # wave, scheduling every size, with no bound.
    state = _state(**WAVE_STATES[name])
    optimized = _tomato_plan(state)
    request.getfixturevalue("reference")
    reference = _tomato_plan(state)

    assert optimized == reference
    if reference is not None:
        planted = sum(a.action_type == PLANT for a in optimized.plan.actions())
        assert planted == sum(a.action_type == PLANT for a in reference.plan.actions())


@pytest.mark.parametrize("name", list(WAVE_STATES))
def test_no_wave_above_the_bound_is_ever_feasible(name):
    state = _state(**WAVE_STATES[name])
    bound = max_tomato_plantings(state)
    held = state.player.seeds.get("TOMATO", 0)

    for size in range(bound + 1, min(tomato_program_limit(state), bound + 4) + 1):
        hypothesis = Hypothesis("TOMATO", plant=size, buy=0 if held else size)
        assert FarmScheduler().schedule(state, hypothesis) is None


def test_wave_feasibility_is_not_monotone_so_the_search_stays_a_decrement():
    # Six far-reaching plantings fit where five do not: smaller is not
    # always feasible, so no bisection over the wave size is safe.
    state = _state(**WAVE_STATES["far plants day 18"])
    feasible = {k: FarmScheduler().schedule(state, Hypothesis("TOMATO", plant=k, buy=k)) is not None for k in (5, 6)}

    assert feasible == {5: False, 6: True}


# --- generators and continuation against the reference stack ------------


@pytest.mark.parametrize("kwargs", list(WAVE_STATES.values()), ids=list(WAVE_STATES))
def test_generated_plans_and_states_match_the_reference(kwargs, request):
    state = _state(**kwargs)
    optimized = [
        g
        for gen, opp in ((WheatPlanGenerator(), WHEAT), (TomatoPlanGenerator(), TOMATO))
        for g in gen.generate_with_states(state, opp)
    ]
    request.getfixturevalue("reference")
    reference = [
        g
        for gen, opp in ((WheatPlanGenerator(), WHEAT), (TomatoPlanGenerator(), TOMATO))
        for g in gen.generate_with_states(state, opp)
    ]

    assert optimized == reference


@pytest.mark.parametrize("day", [0, 15, 20, 24, 28])
def test_continuation_matches_the_reference(day, request):
    state = _state(step=24 * day)
    optimized = ContinuationEvaluator().evaluate(state)
    request.getfixturevalue("reference")
    reference = ContinuationEvaluator().evaluate(state)

    assert optimized == reference


def test_starting_state_result_is_unchanged():
    evaluation = ContinuationEvaluator().evaluate(_state())

    assert evaluation.projected_terminal_cash == 8005
    assert evaluation.continuation_plans_considered == 32
    assert [p.label for p in evaluation.plans] == [
        "WHEAT at (4, 4)", "WHEAT at (4, 4)", "TOMATO wave of 21",
    ]


# --- copy-on-write ------------------------------------------------------


def test_fast_path_results_are_still_isolated():
    state = _state(step=5, tiles={SPAWN: _plant("TOMATO", 0, watered=True)})
    snapshot = copy.deepcopy(state)

    result = Simulator().play_turn(state, Turn())
    result.player.farm.farmer.append(0)
    result.opponent.farm.hands.append([0, 0])
    result.player.seeds["WHEAT"] = 9
    result.raw_observation["day"] = 99

    assert result.player.farm is not state.player.farm
    assert result.opponent is not state.opponent
    assert state == snapshot


def test_unisolated_fast_path_shares_only_what_did_not_change():
    state = Simulator().play_turn(_state(step=5), Turn())

    chained = Simulator().play_turn(state, Turn(), isolated=False)

    assert chained.player.farm is state.player.farm
    assert chained.opponent is state.opponent
    assert chained.step == state.step + 1


# --- the real environment -----------------------------------------------


def test_real_environment_matches_every_turn_across_the_decay_boundary():
    """Leave a wheat unharvested and compare every turn through its decay (from step 120)."""
    kaggle_environments = pytest.importorskip("kaggle_environments")
    schedule = {0: Turn(market=(Action(BUY_SEED, "WHEAT", 1),)), 1: Turn(farmer=Action(PLANT, "WHEAT")), 2: Turn(farmer=Action(WATER))}
    schedule.update({24 * d: Turn(farmer=Action(WATER)) for d in range(1, 5)})
    received = {}
    operator = Operator()

    def agent(obs):
        received[obs["step"]] = copy.deepcopy(dict(obs))
        return operator.execute(Decision(turn=schedule.get(obs["step"], Turn())))

    env = kaggle_environments.make(
        "kaggriculture",
        configuration={"episodeSteps": 140, "weedSpawnChance": 0, "townShopUnlockInterval": 10_000, "seed": 43},
        debug=True,
    )
    env.run([agent, "pass"])

    state = parse(received[0])
    for step in range(0, 136):
        state = Simulator().play_turn(state, schedule.get(step, Turn()), isolated=False)
        real = parse(received[step + 1])
        assert (state.step, state.player, state.market) == (real.step, real.player, real.market), step
    assert isinstance(state.player.farm.tiles[4][4], WeedTile)
