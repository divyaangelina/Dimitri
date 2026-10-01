"""Tests for the Simulator's PLANT behavior on the factual farm state.

These tests use GameStates produced by the real Parser, so tiles are
the typed models from dimitri.models.tile. PLANT is checked against the
installed Kaggriculture environment's rules (``_apply_unit_action`` and
``_new_plant``), including a parity test that plays a real environment
step and compares its result with the Simulator's prediction.
"""

import copy
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from dimitri.models.tile import AnimalTile, PlantTile, StructureTile, WeedTile
from dimitri.observer.parser import parse
from dimitri.planner.action import BUY_PRODUCT, PLANT, SELL, Action
from dimitri.planner.generator import CandidateGenerator
from dimitri.planner.planner import Planner
from dimitri.planner.rules import buy_quote, new_plant
from dimitri.planner.simulator import Simulator
from dimitri.planner.turn import Turn
from dimitri.utils.constants import CROPS, TURNS_PER_DAY

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"

PLANT_DICT = {
    "kind": "PLANT",
    "crop": "CARROT",
    "planted_day": 0,
    "watered_today": False,
    "consecutive_unwatered": 1,
    "yield_units": 1,
    "max_lifespan_step": 96,
    "fertilized_until_day": -1,
}
ANIMAL_DICT = {
    "kind": "COOP",
    "animal": "GOOSE",
    "placed_day": 0,
    "yield_units": 0,
    "consecutive_unfed": 0,
    "fed_today": False,
    "cared_today": False,
    "fertilizer_available": False,
    "pending_care_bonus": 0,
}


def _observation(*, seeds=None, day=0, farmer=(4, 4), hands=(), tiles=None) -> dict:
    """Sample observation with Dimitri's farm, seeds, and day overridden."""
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)
    farm = observation["farms"][0]
    farm["farmer"] = list(farmer)
    farm["hands"] = [list(h) for h in hands]
    for (x, y), tile in (tiles or {}).items():
        farm["tiles"][y][x] = tile
    observation["private"]["seeds"].update(seeds or {"WHEAT": 2, "TOMATO": 1})
    observation["private"]["inventories"] = [{} for _ in range(1 + len(hands))]
    observation["day"] = day
    observation["hour"] = 5
    observation["step"] = day * TURNS_PER_DAY + 5
    return observation


def _state(**kwargs):
    return parse(_observation(**kwargs))


def _plant(state, crop, *, unit=0, quantity=1):
    return Simulator().simulate(state, Action(PLANT, crop, quantity), unit=unit)


# --- valid PLANT --------------------------------------------------------


def test_plant_places_plant_tile_under_farmer():
    state = _state(day=3)

    result = _plant(state, "WHEAT")

    assert result.player.farm.tiles[4][4] == PlantTile(
        crop="WHEAT",
        planted_day=3,
        watered_today=False,
        consecutive_unwatered=1,
        yield_units=1,
        max_lifespan_step=(3 + 4 + 1) * TURNS_PER_DAY,
        fertilized_until_day=-1,
    )


def test_plant_ongoing_crop_matches_environment_initial_state():
    result = _plant(_state(day=2), "TOMATO")

    tile = result.player.farm.tiles[4][4]
    assert tile.yield_units == 0
    assert tile.max_lifespan_step == -1


def test_plant_uses_one_seed_of_that_crop_only():
    result = _plant(_state(), "WHEAT")

    assert result.player.seeds["WHEAT"] == 1
    assert result.player.seeds["TOMATO"] == 1


def test_plant_changes_no_other_tile():
    state = _state()

    result = _plant(state, "WHEAT")

    before, after = state.player.farm.tiles, result.player.farm.tiles
    changed = [
        (x, y)
        for y, row in enumerate(after)
        for x, tile in enumerate(row)
        if tile != before[y][x]
    ]
    assert changed == [(4, 4)]


def test_plant_leaves_money_shed_unit_inventories_and_shared_state_unchanged():
    state = _state()

    result = _plant(state, "WHEAT")

    assert result.player.money == state.player.money
    assert result.player.inventory == state.player.inventory
    assert result.player.unit_inventories == state.player.unit_inventories
    assert replace(result.player.farm, tiles=None) == replace(
        state.player.farm, tiles=None
    )
    assert result.opponent == state.opponent
    assert result.market == state.market
    assert result.town == state.town
    assert (result.step, result.day, result.hour) == (state.step, state.day, state.hour)
    assert result.raw_observation == state.raw_observation


def test_hand_plants_on_its_own_tile():
    state = _state(hands=[(2, 3)])

    result = _plant(state, "WHEAT", unit=1)

    assert isinstance(result.player.farm.tiles[3][2], PlantTile)
    assert result.player.farm.tiles[4][4] is None


def test_new_plant_matches_environment_for_every_crop():
    env = pytest.importorskip("kaggle_environments.envs.kaggriculture.kaggriculture")

    for crop in env.CROPS:
        raw = env._new_plant(crop, 5, TURNS_PER_DAY)
        assert new_plant(crop, 5) == PlantTile(
            **{k: v for k, v in raw.items() if k != "kind"}
        )


def test_crop_constants_match_environment():
    env = pytest.importorskip("kaggle_environments.envs.kaggriculture.kaggriculture")
    spec = json.loads(
        (Path(env.__file__).parent / "kaggriculture.json").read_text()
    )

    assert set(CROPS) == set(env.CROPS)
    for crop, rules in CROPS.items():
        assert rules.max_yield_day == env.CROPS[crop]["max_yield_day"]
        assert rules.ongoing == env.CROPS[crop]["ongoing"]
    assert TURNS_PER_DAY == spec["configuration"]["turnsPerDay"]["default"]


def test_plant_matches_a_real_environment_step():
    """Simulated PLANT equals what the environment does on the next step."""
    kaggle_environments = pytest.importorskip("kaggle_environments")
    received = []

    def agent(obs):
        received.append(copy.deepcopy(dict(obs)))
        if obs["step"] == 0:
            return {"farmer": ["PASS"], "hands": [], "market": [["BUY_SEED", "WHEAT", 1]]}
        return {"farmer": ["PLANT", "WHEAT"], "hands": [], "market": []}

    env = kaggle_environments.make(
        "kaggriculture", configuration={"episodeSteps": 4}, debug=True
    )
    env.run([agent, "pass"])
    before = parse(received[1])  # step 1: seed bought, farmer on an empty tile
    after = parse(received[2])  # step 2: the environment applied PLANT

    predicted = _plant(before, "WHEAT")

    assert predicted.player.farm.tiles == after.player.farm.tiles
    assert predicted.player.seeds == after.player.seeds
    assert predicted.player.money == after.player.money


# --- invalid PLANT ------------------------------------------------------


@pytest.mark.parametrize(
    "occupant",
    [
        "LOCKED",
        PLANT_DICT,
        {"kind": "WEED"},
        {"kind": "PASTURE"},
        ANIMAL_DICT,
    ],
)
def test_plant_on_non_empty_tile_raises(occupant):
    state = _state(tiles={(4, 4): occupant})

    with pytest.raises(ValueError, match="non-empty tile"):
        _plant(state, "WHEAT")


def test_occupants_are_typed_tile_models():
    state = _state(
        tiles={(0, 0): PLANT_DICT, (1, 0): {"kind": "WEED"}, (2, 0): {"kind": "COOP"}, (3, 0): ANIMAL_DICT}
    )

    row = state.player.farm.tiles[0]
    assert [type(t) for t in row[:4]] == [PlantTile, WeedTile, StructureTile, AnimalTile]


def test_plant_without_seed_raises():
    with pytest.raises(ValueError, match="No 'CARROT' seeds"):
        _plant(_state(), "CARROT")


def test_plant_unknown_crop_raises():
    with pytest.raises(ValueError, match="Unknown crop"):
        _plant(_state(seeds={"CACTUS": 3}), "CACTUS")


@pytest.mark.parametrize("quantity", [0, 2, True])
def test_plant_quantity_other_than_one_raises(quantity):
    with pytest.raises(ValueError, match="exactly one seed"):
        _plant(_state(), "WHEAT", quantity=quantity)


def test_plant_by_missing_hand_raises():
    with pytest.raises(ValueError, match="Unit 1 does not exist"):
        _plant(_state(), "WHEAT", unit=1)


def test_failed_plant_does_not_mutate_original():
    state = _state(tiles={(4, 4): "LOCKED"})
    snapshot = copy.deepcopy(state)

    with pytest.raises(ValueError):
        _plant(state, "WHEAT")

    assert state == snapshot


# --- immutability -------------------------------------------------------


def test_plant_does_not_mutate_original_state():
    state = _state()
    snapshot = copy.deepcopy(state)

    _plant(state, "WHEAT")

    assert state == snapshot
    assert state.player.farm.tiles[4][4] is None


def test_simulated_tile_grid_is_immutable():
    result = _plant(_state(), "WHEAT")
    tiles = result.player.farm.tiles

    assert isinstance(tiles, tuple) and all(isinstance(row, tuple) for row in tiles)
    with pytest.raises(TypeError):
        tiles[4][4] = None
    with pytest.raises(FrozenInstanceError):
        tiles[4][4].yield_units = 99


# --- simulate_turn ------------------------------------------------------


def test_simulate_turn_plants_for_farmer_and_hands_then_trades():
    state = _state(hands=[(1, 1)])
    state = replace(state, player=replace(state.player, money=100))
    turn = Turn(
        farmer=Action(PLANT, "WHEAT"),
        hands=(Action(PLANT, "TOMATO"),),
        market=(Action(BUY_PRODUCT, "WHEAT"),),
    )

    result = Simulator().simulate_turn(state, turn)

    assert result.player.farm.tiles[4][4].crop == "WHEAT"
    assert result.player.farm.tiles[1][1].crop == "TOMATO"
    assert result.player.seeds["WHEAT"] == 1
    assert result.player.seeds["TOMATO"] == 0
    assert result.player.money == 100 - buy_quote("WHEAT", state.market.inventory["WHEAT"])


def test_simulate_turn_rejects_more_plants_than_seeds():
    state = _state(seeds={"WHEAT": 1}, hands=[(1, 1)])
    turn = Turn(farmer=Action(PLANT, "WHEAT"), hands=(Action(PLANT, "WHEAT"),))

    with pytest.raises(ValueError, match="No 'WHEAT' seeds"):
        Simulator().simulate_turn(state, turn)


def test_simulate_turn_rejects_two_units_planting_one_tile():
    state = _state(hands=[(4, 4)])
    turn = Turn(farmer=Action(PLANT, "WHEAT"), hands=(Action(PLANT, "WHEAT"),))

    with pytest.raises(ValueError, match="non-empty tile"):
        Simulator().simulate_turn(state, turn)


def test_simulate_turn_rejects_market_action_for_a_unit():
    with pytest.raises(ValueError, match="cannot be performed by a unit"):
        Simulator().simulate_turn(_state(), Turn(farmer=Action(SELL, "WHEAT")))


def test_simulate_turn_rejects_farm_work_in_market():
    with pytest.raises(ValueError, match="not a market action"):
        Simulator().simulate_turn(_state(), Turn(market=(Action(PLANT, "WHEAT"),)))


def test_single_action_turn_matches_simulate():
    state = _state()
    action = Action(PLANT, "WHEAT")

    assert Simulator().simulate_turn(state, Turn.from_action(action)) == Simulator().simulate(
        state, action
    )


# --- compatibility with generation and planning ------------------------


def test_generator_skips_plant_when_farmer_tile_is_occupied():
    planted = _plant(_state(), "WHEAT")

    actions = CandidateGenerator().generate(planted)

    assert all(action.action_type != PLANT for action in actions)


def test_generator_skips_plant_on_locked_tile():
    actions = CandidateGenerator().generate(_state(tiles={(4, 4): "LOCKED"}))

    assert all(action.action_type != PLANT for action in actions)


def test_planner_handles_state_after_planting():
    planted = _plant(_state(), "WHEAT")

    result = Planner().plan(planted)

    assert result.candidates
