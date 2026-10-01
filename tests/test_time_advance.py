"""Tests for time advancement: Simulator.advance_turn and Simulator.play_turn.

Rules come from the installed Kaggriculture environment's
``interpreter``: after units and market orders, each turn applies town
consumption and a price refresh, plant decay, the end-of-day sweep on a
day's last turn, and then ``step`` advances. The end-of-day sweep
refreshes plants and animals, drops carried items into the shed, returns
the farmer to spawn, dismisses hands, and resets ``hires_today``.

Rule functions are checked against the environment's own functions on
many inputs, and full games are played for real and compared turn by
turn. Weed spawning is random, so the real games disable it; town-shop
unlocks are random too, so ``town`` is not compared on those turns.
"""

import copy
import itertools
import json
from dataclasses import replace
from pathlib import Path

import pytest

from dimitri.models.inventory import Inventory
from dimitri.models.tile import AnimalTile, PlantTile, StructureTile, WeedTile
from dimitri.observer.parser import parse
from dimitri.pipeline import Pipeline
from dimitri.planner.action import HARVEST, PLANT, WATER, Action
from dimitri.planner.planner import Planner
from dimitri.planner.rules import FARMER, harvest_blocker, water_blocker
from dimitri.planner.simulator import Simulator
from dimitri.planner.time_rules import (
    animal_at_end_of_day,
    decayed_tile,
    plant_at_end_of_day,
    spawn_position,
    town_consumption,
)
from dimitri.planner.turn import Turn
from dimitri.utils.constants import ANIMALS, CROPS, SHOPS, TURNS_PER_DAY

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"
SPAWN = (4, 4)
FIELD = (2, 2)


def _observation(*, step=5, farmer=FIELD, hands=(), tiles=None, shed=None, carried=None,
                 shops=(), opponent_tiles=None, opponent_farmer=None):
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)
    observation["step"] = step
    observation["day"], observation["hour"] = divmod(step, TURNS_PER_DAY)
    player = observation["player"]
    farm = observation["farms"][player]
    farm["farmer"] = list(farmer)
    farm["hands"] = [list(h) for h in hands]
    farm["hires_today"] = len(hands)
    for (x, y), tile in (tiles or {}).items():
        farm["tiles"][y][x] = copy.deepcopy(tile)
    opponent = observation["farms"][1 - player]
    for (x, y), tile in (opponent_tiles or {}).items():
        opponent["tiles"][y][x] = copy.deepcopy(tile)
    if opponent_farmer is not None:
        opponent["farmer"] = list(opponent_farmer)
    private = observation["private"]
    if shed is not None:
        private["shed"] = shed
    private["inventories"] = (
        [{} for _ in range(1 + len(hands))] if carried is None else carried
    )
    observation["town"]["unlocked_shops"] = list(shops)
    return observation


def _state(**kwargs):
    return parse(_observation(**kwargs))


def _plant(crop="WHEAT", planted_day=0, **fields):
    plant = {
        "kind": "PLANT",
        "crop": crop,
        "planted_day": planted_day,
        "watered_today": False,
        "consecutive_unwatered": 0,
        "yield_units": 1,
        "max_lifespan_step": -1 if CROPS[crop].ongoing else (planted_day + CROPS[crop].max_yield_day + 1) * 24,
        "fertilized_until_day": -1,
    }
    plant.update(fields)
    return plant


def _tile(state, position=FIELD):
    x, y = position
    return state.player.farm.tiles[y][x]


def _advance(state, turns=1):
    for _ in range(turns):
        state = Simulator().advance_turn(state)
    return state


# --- time ----------------------------------------------------------------


def test_one_turn_advances_step_and_hour():
    result = _advance(_state(step=5))

    assert (result.step, result.day, result.hour) == (6, 0, 6)


def test_hour_rolls_over_into_the_next_day():
    result = _advance(_state(step=23))

    assert (result.step, result.day, result.hour) == (24, 1, 0)


def test_later_day_rolls_over():
    result = _advance(_state(step=24 * 7 + 23))

    assert (result.step, result.day, result.hour) == (24 * 8, 8, 0)


def test_many_consecutive_turns():
    result = _advance(_state(step=10), turns=24 * 2 + 3)

    assert (result.step, result.day, result.hour) == (61, 2, 13)


def test_play_turn_advances_time_exactly_once():
    state = _state(step=5)

    result = Simulator().play_turn(state, Turn())

    assert result.step == state.step + 1
    assert result == Simulator().advance_turn(Simulator().simulate_turn(state, Turn()))


def test_play_turn_applies_actions_before_the_end_of_turn():
    # Harvested on the day's last turn, the crop is dropped into the shed that night.
    state = _state(step=24 * 3 + 23, tiles={FIELD: _plant(yield_units=3)}, shed={})

    result = Simulator().play_turn(state, Turn(farmer=Action(HARVEST)))

    assert _tile(result) is None
    assert result.player.inventory.items == {"WHEAT": 3}
    assert result.player.unit_inventories == (Inventory(items={}),)


def test_simulate_turn_still_does_not_advance_time():
    state = _state(step=23)

    result = Simulator().simulate_turn(state, Turn(farmer=Action("NORTH")))

    assert (result.step, result.day, result.hour) == (23, 0, 23)


def test_advance_turn_does_not_mutate_original():
    state = _state(step=23, tiles={FIELD: _plant()}, carried=[{"WHEAT": 2}])
    before = copy.deepcopy(state)

    _advance(state)

    assert state == before


# --- market --------------------------------------------------------------


def test_town_center_consumes_every_twelfth_step():
    assert town_consumption(12, 0, ())["EGG"] == 1
    assert town_consumption(13, 0, ()) == {}
    assert "FERTILIZER" not in town_consumption(12, 0, ())


@pytest.mark.parametrize(("day", "units"), [(0, 1), (9, 1), (10, 2), (19, 2), (20, 4)])
def test_town_center_demand_grows_with_the_day(day, units):
    assert town_consumption(12 * 50, day, ())["WHEAT"] == units


def test_shops_consume_every_fourth_step():
    consumed = town_consumption(4, 0, ("BAKERY", "YARN_STORE"))

    # A single-product shop consumes 2 of it.
    assert consumed == {"EGG": 1, "WHEAT": 1, "WOOL": 2}
    assert town_consumption(5, 0, ("BAKERY",)) == {}


def test_advance_turn_applies_consumption_and_refreshes_prices():
    state = _state(step=12, shops=("PET_CAFE",))

    result = _advance(state)

    assert result.market.inventory["CARROT"] == state.market.inventory["CARROT"] - 3
    assert result.market.inventory["FERTILIZER"] == state.market.inventory["FERTILIZER"]
    assert result.market.prices["CARROT"] > state.market.prices["CARROT"]


def test_town_consumption_matches_environment():
    env = pytest.importorskip("kaggle_environments.envs.kaggriculture.kaggriculture")

    for step, shops in itertools.product(range(0, 49), [(), tuple(SHOPS)]):
        market = {"inventory": {p: 10000 for p in env.PRODUCTS}, "prices": {}}
        fake_env = type("Env", (), {"configuration": {}})()
        fake_state = [type("S", (), {})()]
        fake_state[0].observation = type("O", (), {})()
        fake_state[0].observation.market = market
        fake_state[0].observation.town = {"unlocked_shops": list(shops)}
        env._town_consume(fake_env, fake_state, step)

        consumed = town_consumption(step, step // 24, shops)
        for product in env.PRODUCTS:
            assert 10000 - market["inventory"][product] == consumed.get(product, 0)


# --- decay ---------------------------------------------------------------


def test_decay_starts_at_the_lifespan_step_and_repeats_every_second_step():
    plant = PlantTile("WHEAT", 0, False, 0, 3, max_lifespan_step=120, fertilized_until_day=-1)

    assert decayed_tile(plant, 119) == plant
    assert decayed_tile(plant, 120).yield_units == 2
    assert decayed_tile(plant, 121) == plant
    assert decayed_tile(plant, 122).yield_units == 2


def test_decay_to_zero_yield_leaves_a_weed():
    plant = PlantTile("WHEAT", 0, False, 0, 1, max_lifespan_step=120, fertilized_until_day=-1)

    assert decayed_tile(plant, 120) == WeedTile()


def test_plant_without_lifespan_never_decays():
    plant = PlantTile("TOMATO", 0, False, 0, 2, max_lifespan_step=-1, fertilized_until_day=-1)

    assert decayed_tile(plant, 10_000) == plant


def test_decay_matches_environment():
    env = pytest.importorskip("kaggle_environments.envs.kaggriculture.kaggriculture")

    for lifespan, yield_units, step in itertools.product((-1, 96, 120), (0, 1, 2, 5), range(90, 130)):
        raw = _plant(yield_units=yield_units, max_lifespan_step=lifespan)
        farm = {"tiles": [[copy.deepcopy(raw)]]}
        env._decay_plants(farm, step)

        expected = parse_tile(farm["tiles"][0][0])
        assert decayed_tile(parse_tile(raw), step) == expected


def parse_tile(raw):
    observation = _observation(tiles={(0, 0): raw})
    return parse(observation).player.farm.tiles[0][0]


# --- plants at end of day ------------------------------------------------


def test_watered_plant_resets_its_unwatered_streak():
    plant = parse_tile(_plant(watered_today=True, consecutive_unwatered=1))

    result = plant_at_end_of_day(plant, 1)

    assert (result.watered_today, result.consecutive_unwatered) == (False, 0)


def test_one_unwatered_day_is_survived():
    result = plant_at_end_of_day(parse_tile(_plant(consecutive_unwatered=0)), 1)

    assert isinstance(result, PlantTile)
    assert result.consecutive_unwatered == 1


def test_second_unwatered_day_turns_plant_into_weed():
    assert plant_at_end_of_day(parse_tile(_plant(consecutive_unwatered=1)), 1) == WeedTile()


def test_plant_unwatered_on_its_planting_day_becomes_a_weed():
    # A new plant starts at consecutive_unwatered 1: planting day counts as unwatered.
    plant = parse_tile(_plant(consecutive_unwatered=1, planted_day=0))

    assert plant_at_end_of_day(plant, 0) == WeedTile()


@pytest.mark.parametrize("crop", ["WHEAT", "CARROT", "MELON"])
def test_one_time_crops_never_produce_at_end_of_day(crop):
    plant = parse_tile(_plant(crop, watered_today=True, yield_units=1))

    for day in range(20):
        assert plant_at_end_of_day(plant, day).yield_units == 1


def test_tomato_produces_daily_from_its_first_yield_day():
    # TOMATO: first_yield_day 8, interval 1, max_yield 4.
    plant = parse_tile(_plant("TOMATO", watered_today=True, yield_units=0))

    produced = [day for day in range(20) if plant_at_end_of_day(plant, day).yield_units]

    assert produced == [7, 8, 9, 10]


def test_strawberry_produces_every_second_day_from_its_first_yield_day():
    # STRAWBERRY: first_yield_day 10, interval 2, max_yield 4.
    plant = parse_tile(_plant("STRAWBERRY", watered_today=True, yield_units=0))

    produced = [day for day in range(30) if plant_at_end_of_day(plant, day).yield_units]

    assert produced == [9, 11, 13, 15]


def test_last_production_sets_the_ongoing_lifespan():
    plant = parse_tile(_plant("TOMATO", watered_today=True, yield_units=0))

    assert plant_at_end_of_day(plant, 9).max_lifespan_step == -1
    assert plant_at_end_of_day(plant, 10).max_lifespan_step == (11 + 1) * 24


def test_ongoing_crop_produces_even_when_unwatered():
    plant = parse_tile(_plant("TOMATO", consecutive_unwatered=0, yield_units=0))

    assert plant_at_end_of_day(plant, 7).yield_units == 1


def test_fertilized_watered_production_doubles():
    plant = parse_tile(_plant("TOMATO", watered_today=True, yield_units=0, fertilized_until_day=7))

    assert plant_at_end_of_day(plant, 7).yield_units == 2


def test_fertilizer_needs_watering_to_double():
    plant = parse_tile(_plant("TOMATO", yield_units=0, fertilized_until_day=7))

    assert plant_at_end_of_day(plant, 7).yield_units == 1


def test_ongoing_production_is_capped_at_max_yield():
    plant = parse_tile(_plant("TOMATO", watered_today=True, yield_units=4))

    assert plant_at_end_of_day(plant, 8).yield_units == 4


_PLANT_FIELD_VALUES = {
    "planted_day": (0, 3),
    "watered_today": (False, True),
    "consecutive_unwatered": (0, 1),
    "yield_units": (0, 1, 3, 6),
    "fertilized_until_day": (-1, 9, 14),
}


@pytest.mark.parametrize("crop", sorted(CROPS))
def test_plant_end_of_day_matches_environment_for_every_crop(crop):
    env = pytest.importorskip("kaggle_environments.envs.kaggriculture.kaggriculture")
    names = list(_PLANT_FIELD_VALUES)

    for values in itertools.product(*_PLANT_FIELD_VALUES.values()):
        raw = _plant(crop, **dict(zip(names, values)))
        for day in range(0, 24):
            farm = {"tiles": [[copy.deepcopy(raw)]]}
            env._daily_refresh_plants(farm, day, 24)

            assert plant_at_end_of_day(parse_tile(raw), day) == parse_tile(farm["tiles"][0][0])


# --- animals at end of day -----------------------------------------------


def _animal(animal="GOOSE", **fields):
    raw = {
        "kind": ANIMALS[animal].structure,
        "animal": animal,
        "placed_day": 0,
        "yield_units": 0,
        "fed_today": True,
        "consecutive_unfed": 0,
        "cared_today": False,
        "fertilizer_available": False,
        "pending_care_bonus": 0,
    }
    raw.update(fields)
    return raw


def test_unfed_animal_escapes_on_its_second_unfed_day():
    result = animal_at_end_of_day(parse_tile(_animal(fed_today=False, consecutive_unfed=1)), 2)

    assert result == StructureTile("COOP")


def test_fed_and_cared_animal_banks_a_bonus_paid_on_production():
    animal = parse_tile(_animal(cared_today=True))

    banked = animal_at_end_of_day(animal, 0)
    assert (banked.pending_care_bonus, banked.yield_units) == (1, 0)

    fed = replace(banked, fed_today=True)
    paid = animal_at_end_of_day(fed, 3)  # GOOSE first produces on day 4 of its age.
    assert (paid.yield_units, paid.pending_care_bonus) == (2, 0)


def test_unfed_production_day_forfeits_the_bonus():
    animal = parse_tile(_animal(fed_today=False, pending_care_bonus=3))

    result = animal_at_end_of_day(animal, 3)

    assert (result.yield_units, result.pending_care_bonus) == (1, 0)


@pytest.mark.parametrize("animal", sorted(ANIMALS))
def test_animal_end_of_day_matches_environment(animal):
    env = pytest.importorskip("kaggle_environments.envs.kaggriculture.kaggriculture")
    fields = {
        "fed_today": (False, True),
        "cared_today": (False, True),
        "consecutive_unfed": (0, 1),
        "yield_units": (0, 3, 6),
        "pending_care_bonus": (0, 2),
        "fertilizer_available": (False, True),
    }

    for values in itertools.product(*fields.values()):
        raw = _animal(animal, **dict(zip(fields, values)))
        for day in range(0, 14):
            farm = {"tiles": [[copy.deepcopy(raw)]]}
            env._daily_refresh_animals(farm, day)

            expected = parse_tile(farm["tiles"][0][0])
            assert animal_at_end_of_day(parse_tile(raw), day) == expected


def test_advance_turn_refreshes_animals_at_end_of_day():
    state = _state(step=23, tiles={FIELD: _animal(fed_today=True)})

    result = _tile(_advance(state))

    assert isinstance(result, AnimalTile)
    assert (result.fed_today, result.fertilizer_available) == (False, True)


# --- units and carried inventory at end of day ---------------------------


def test_end_of_day_returns_farmer_to_spawn_and_dismisses_hands():
    state = _state(step=23, farmer=(0, 0), hands=[(1, 1), (2, 2)], carried=[{}, {}, {}])

    farm = _advance(state).player.farm

    assert farm.farmer == list(SPAWN) == spawn_position(farm)
    assert (farm.hands, farm.hires_today) == ([], 0)


def test_units_stay_put_before_the_end_of_day():
    state = _state(step=22, farmer=(0, 0), hands=[(1, 1)])

    farm = _advance(state).player.farm

    assert (farm.farmer, farm.hands, farm.hires_today) == ([0, 0], [[1, 1]], 1)


def test_end_of_day_drops_every_carried_inventory_into_the_shed():
    state = _state(
        step=23, hands=[(1, 1)], shed={"EGG": 2}, carried=[{"WHEAT": 3}, {"WHEAT": 1, "MILK": 2}]
    )

    player = _advance(state).player

    assert player.inventory.items == {"EGG": 2, "WHEAT": 4, "MILK": 2}
    assert player.unit_inventories == (Inventory(items={}),)


def test_end_of_day_drop_discards_overflow():
    state = _state(step=23, shed={"EGG": 99}, carried=[{"WHEAT": 3}])

    player = _advance(state).player

    assert player.inventory.items == {"EGG": 99, "WHEAT": 1}
    assert player.unit_inventories == (Inventory(items={}),)


def test_carried_items_stay_carried_before_the_end_of_day():
    state = _state(step=22, carried=[{"WHEAT": 3}])

    assert _advance(state).player.unit_inventories == state.player.unit_inventories


def test_end_of_day_applies_to_the_opponent_farm():
    state = _state(
        step=23,
        opponent_farmer=(0, 0),
        opponent_tiles={FIELD: _plant(consecutive_unwatered=1)},
    )

    opponent = _advance(state).opponent

    assert opponent.farm.farmer == list(SPAWN)
    assert opponent.farm.tiles[FIELD[1]][FIELD[0]] == WeedTile()
    assert opponent.money == state.opponent.money


def test_end_of_day_leaves_money_and_seeds_alone():
    state = _state(step=23, tiles={FIELD: _plant(watered_today=True)})

    result = _advance(state)

    assert result.player.money == state.player.money
    assert result.player.seeds == state.player.seeds


# --- regression: decisions are unchanged ---------------------------------


def test_planner_candidates_do_not_advance_time():
    state = _state(step=23)

    for candidate in Planner().plan(state).candidates:
        assert candidate.resulting_state.step == 23


def test_pipeline_still_chooses_idle_at_the_start():
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)

    assert Pipeline().run(observation) == {"farmer": ["PASS"], "hands": [], "market": []}


# --- the real environment ------------------------------------------------


def _play_crop(crop, *, days, water_until_day=None, harvest_from_day=None, drop=False):
    """Play a real game growing ``crop`` on the spawn tile; return observations and turns.

    The farmer starts each day on the spawn tile, so the crop needs no
    walking. On each turn it plants, waters (on days before
    ``water_until_day``, or always), harvests (from ``harvest_from_day``,
    or never), or drops what it carries, whichever the rules allow first.
    """
    kaggle_environments = pytest.importorskip("kaggle_environments")
    received, sent = {}, {}

    def agent(obs):
        obs = copy.deepcopy(dict(obs))
        step = obs["step"]
        received[step] = obs
        state = parse(obs)
        turn = Turn()
        if step == 0:
            turn = Turn(market=(Action("BUY_SEED", crop, 1),))
        elif _tile(state, SPAWN) is None and state.player.seeds.get(crop, 0):
            turn = Turn(farmer=Action(PLANT, crop))
        elif (water_until_day is None or state.day < water_until_day) and water_blocker(state, FARMER) is None:
            turn = Turn(farmer=Action(WATER))
        elif harvest_from_day is not None and state.day >= harvest_from_day and harvest_blocker(state, FARMER) is None:
            turn = Turn(farmer=Action(HARVEST))
        elif drop and state.player.unit_inventories[0].items:
            turn = Turn(farmer=Action("DROP"))
        sent[step] = turn
        return {
            "farmer": ["PASS"] if turn.farmer is None else [turn.farmer.action_type, *([turn.farmer.target] if turn.farmer.target else [])],
            "hands": [],
            "market": [[a.action_type, a.target, a.quantity] for a in turn.market],
        }

    env = kaggle_environments.make(
        "kaggriculture",
        configuration={"episodeSteps": 24 * days + 2, "weedSpawnChance": 0, "seed": 11},
        debug=True,
    )
    env.run([agent, "pass"])
    return received, sent


def _assert_every_turn_matches(received, sent):
    simulator = Simulator()
    for step in range(max(received)):
        before, after = parse(received[step]), parse(received[step + 1])

        predicted = simulator.play_turn(before, sent[step])

        assert (predicted.step, predicted.day, predicted.hour) == (after.step, after.day, after.hour)
        assert predicted.player == after.player, step
        assert predicted.opponent == after.opponent, step
        assert predicted.market == after.market, step
        # A random shop unlock at the end of every third day is not modelled.
        if not (step % 24 == 23 and (step // 24 + 1) % 3 == 0):
            assert predicted.town == after.town, step


def _crop_tile_history(received):
    return [_tile(parse(received[step]), SPAWN) for step in sorted(received)]


def test_real_environment_game_without_actions_matches_for_three_days():
    kaggle_environments = pytest.importorskip("kaggle_environments")
    received = {}

    def agent(obs):
        received[obs["step"]] = copy.deepcopy(dict(obs))
        return {"farmer": ["PASS"], "hands": [], "market": []}

    env = kaggle_environments.make(
        "kaggriculture",
        configuration={"episodeSteps": 24 * 3 + 2, "weedSpawnChance": 0, "seed": 11},
        debug=True,
    )
    env.run([agent, "pass"])

    _assert_every_turn_matches(received, {step: Turn() for step in received})
    assert parse(received[72]).day == 3


def test_real_environment_plant_left_unwatered_on_planting_day():
    received, sent = _play_crop("WHEAT", days=3, water_until_day=0)

    _assert_every_turn_matches(received, sent)
    assert _tile(parse(received[24]), SPAWN) == WeedTile()


@pytest.mark.parametrize(
    ("crop", "days", "options"),
    [
        ("WHEAT", 7, {"harvest_from_day": 0, "drop": True}),
        ("WHEAT", 8, {}),  # left unharvested: decays to a weed
        ("CARROT", 7, {"harvest_from_day": 5}),  # harvested late, auto-dropped at night
        ("MELON", 15, {"harvest_from_day": 12, "drop": True}),
        ("TOMATO", 14, {"harvest_from_day": 0, "drop": True}),
        ("STRAWBERRY", 19, {"harvest_from_day": 0, "drop": True}),
        ("STRAWBERRY", 2, {"water_until_day": 0}),  # never watered
        ("TOMATO", 6, {"water_until_day": 3}),  # watering stops
    ],
    ids=[
        "wheat-harvested",
        "wheat-unharvested",
        "carrot-late",
        "melon",
        "tomato-productions",
        "strawberry-productions",
        "strawberry-unwatered",
        "tomato-watering-stops",
    ],
)
def test_real_environment_crop_growth_matches(crop, days, options):
    received, sent = _play_crop(crop, days=days, **options)

    _assert_every_turn_matches(received, sent)
    assert any(isinstance(t, PlantTile) for t in _crop_tile_history(received))


def test_real_environment_ongoing_crops_produce_repeatedly():
    received, sent = _play_crop("STRAWBERRY", days=19, harvest_from_day=0, drop=True)
    harvests = [step for step, turn in sent.items() if turn.farmer == Action(HARVEST)]

    # Four productions on days 10, 12, 14, 16, each harvested the next morning.
    assert [step // 24 for step in harvests] == [10, 12, 14, 16]
    assert parse(received[max(received)]).player.inventory.items["STRAWBERRY"] == 4


def test_real_environment_unwatered_crop_becomes_weed_overnight():
    received, _ = _play_crop("STRAWBERRY", days=2, water_until_day=0)

    assert isinstance(_tile(parse(received[23]), SPAWN), PlantTile)
    assert _tile(parse(received[24]), SPAWN) == WeedTile()
