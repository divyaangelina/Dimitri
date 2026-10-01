"""Unit tests for observed game-state fields: step, town, and unit inventories.

Raw shapes follow the installed Kaggriculture environment: ``step`` is
supplied by the kaggle-environments framework, ``town`` is
``{"unlocked_shops": [str, ...]}`` (``_new_town``), and
``private.inventories`` is ``[main_farmer_inv, hand1_inv, ...]`` where
each entry is an ``{item: count}`` dict (``_new_private``, ``_do_hire``,
``_farmer_inventory``). One test plays a short real game and parses
every observation the agents received.
"""

import copy
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from dimitri.models.inventory import Inventory
from dimitri.models.opponent import Opponent
from dimitri.models.tile import PlantTile
from dimitri.models.town import Town
from dimitri.observer.observer import Observer
from dimitri.observer.parser import ParseError, parse
from dimitri.observer.validator import ValidationError, validate

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"


def _load_sample_observation() -> dict:
    with SAMPLE_OBSERVATION_PATH.open() as f:
        return json.load(f)


# --- step ---------------------------------------------------------------


def test_step_is_parsed_from_sample_observation():
    observation = _load_sample_observation()

    assert parse(observation).step == observation["step"] == 0


def test_step_is_parsed_independently_of_day_and_hour():
    observation = _load_sample_observation()
    observation.update(step=79, day=3, hour=7)

    game_state = parse(observation)

    assert (game_state.step, game_state.day, game_state.hour) == (79, 3, 7)


def test_missing_step_raises_parse_error():
    observation = _load_sample_observation()
    del observation["step"]

    with pytest.raises(ParseError, match="Missing 'step'"):
        parse(observation)


@pytest.mark.parametrize("bad_step", ["0", 1.5, True, None])
def test_non_int_step_raises_parse_error(bad_step):
    observation = _load_sample_observation()
    observation["step"] = bad_step

    with pytest.raises(ParseError, match="'step'"):
        parse(observation)


def test_validator_rejects_non_int_step():
    game_state = replace(parse(_load_sample_observation()), step="0")

    with pytest.raises(ValidationError, match="GameState.step"):
        validate(game_state)


# --- town ---------------------------------------------------------------


def test_empty_town_is_parsed_from_sample_observation():
    assert parse(_load_sample_observation()).town == Town(unlocked_shops=())


def test_unlocked_shops_are_parsed_in_order():
    observation = _load_sample_observation()
    observation["town"]["unlocked_shops"] = ["BAKERY", "PET_CAFE"]

    assert parse(observation).town == Town(unlocked_shops=("BAKERY", "PET_CAFE"))


def test_town_is_immutable_and_does_not_alias_observation():
    observation = _load_sample_observation()
    observation["town"]["unlocked_shops"] = ["BAKERY"]
    town = parse(observation).town

    observation["town"]["unlocked_shops"].append("YARN_STORE")

    assert town.unlocked_shops == ("BAKERY",)
    with pytest.raises(FrozenInstanceError):
        town.unlocked_shops = ()
    with pytest.raises(AttributeError):
        town.unlocked_shops.append("YARN_STORE")


def test_missing_town_raises_parse_error():
    observation = _load_sample_observation()
    del observation["town"]

    with pytest.raises(ParseError, match="Missing 'town'"):
        parse(observation)


def test_missing_unlocked_shops_raises_parse_error():
    observation = _load_sample_observation()
    observation["town"] = {}

    with pytest.raises(ParseError, match="Missing 'unlocked_shops'"):
        parse(observation)


@pytest.mark.parametrize(
    ("shops", "message"),
    [("BAKERY", "Expected a sequence"), ([3], "Expected str"), ([None], "Expected str")],
)
def test_malformed_unlocked_shops_raise_parse_error(shops, message):
    observation = _load_sample_observation()
    observation["town"]["unlocked_shops"] = shops

    with pytest.raises(ParseError, match=message):
        parse(observation)


# --- private unit inventories ------------------------------------------


def test_main_farmer_inventory_is_parsed_from_sample_observation():
    player = parse(_load_sample_observation()).player

    assert player.unit_inventories == (Inventory(items={}),)


def test_unit_inventories_preserve_order_and_contents():
    observation = _load_sample_observation()
    observation["private"]["inventories"] = [{"WHEAT": 1}, {}, {"EGG": 2, "GOOSE": 1}]

    inventories = parse(observation).player.unit_inventories

    assert inventories == (
        Inventory(items={"WHEAT": 1}),
        Inventory(items={}),
        Inventory(items={"EGG": 2, "GOOSE": 1}),
    )


def test_unit_inventories_are_separate_from_shed():
    observation = _load_sample_observation()
    observation["private"]["shed"]["WHEAT"] = 5
    observation["private"]["inventories"] = [{"WHEAT": 1}]

    player = parse(observation).player

    assert player.inventory.items["WHEAT"] == 5
    assert player.unit_inventories[0].items == {"WHEAT": 1}


def test_unit_inventories_are_immutable_and_do_not_alias_observation():
    observation = _load_sample_observation()
    observation["private"]["inventories"] = [{"WHEAT": 1}]
    player = parse(observation).player

    observation["private"]["inventories"][0]["WHEAT"] = 99
    observation["private"]["inventories"].append({"EGG": 1})

    assert player.unit_inventories == (Inventory(items={"WHEAT": 1}),)
    assert isinstance(player.unit_inventories, tuple)
    with pytest.raises(FrozenInstanceError):
        player.unit_inventories = ()
    with pytest.raises(FrozenInstanceError):
        player.unit_inventories[0].items = {}


def test_missing_inventories_raises_parse_error():
    observation = _load_sample_observation()
    del observation["private"]["inventories"]

    with pytest.raises(ParseError, match="Missing 'inventories'"):
        parse(observation)


@pytest.mark.parametrize(
    ("inventories", "message"),
    [({"WHEAT": 1}, "Expected a sequence"), ([["WHEAT"]], "Expected a mapping")],
)
def test_malformed_inventories_raise_parse_error(inventories, message):
    observation = _load_sample_observation()
    observation["private"]["inventories"] = inventories

    with pytest.raises(ParseError, match=message):
        parse(observation)


def test_validator_rejects_non_int_unit_inventory_counts():
    observation = _load_sample_observation()
    observation["private"]["inventories"] = [{"WHEAT": "1"}]

    with pytest.raises(ValidationError, match=r"Player.unit_inventories\[0\]"):
        Observer().observe(observation)


# --- public / private / opponent separation ----------------------------


def test_private_state_lives_only_on_player():
    game_state = parse(_load_sample_observation())

    assert not hasattr(game_state.opponent, "unit_inventories")
    assert not hasattr(game_state.opponent, "inventory")
    assert not hasattr(game_state.opponent, "seeds")
    assert isinstance(game_state.opponent, Opponent)


def test_shared_state_lives_on_game_state():
    game_state = parse(_load_sample_observation())

    assert isinstance(game_state.town, Town)
    assert not hasattr(game_state.player, "town")
    assert not hasattr(game_state.player, "step")


# --- existing behavior preserved ---------------------------------------


def test_farm_tiles_are_still_parsed_into_models():
    observation = _load_sample_observation()
    observation["farms"][0]["tiles"] = [[{"kind": "WEED"}], [None]]
    observation["farms"][0]["tiles"][0][0] = {
        "kind": "PLANT",
        "crop": "WHEAT",
        "planted_day": 0,
        "watered_today": False,
        "consecutive_unwatered": 1,
        "yield_units": 1,
        "max_lifespan_step": 120,
        "fertilized_until_day": -1,
    }

    tiles = parse(observation).player.farm.tiles

    assert isinstance(tiles[0][0], PlantTile)
    assert tiles[1][0] is None


def test_raw_observation_is_preserved_unchanged():
    observation = _load_sample_observation()
    observation["town"]["unlocked_shops"] = ["BAKERY"]
    observation["private"]["inventories"] = [{"WHEAT": 1}, {}]
    snapshot = copy.deepcopy(observation)

    game_state = parse(observation)

    assert game_state.raw_observation is observation
    assert observation == snapshot


# --- real environment ---------------------------------------------------


def test_every_observation_from_a_real_game_parses():
    """Play a short real game (with a HIRE and a PICKUP) and parse every observation."""
    kaggle_environments = pytest.importorskip("kaggle_environments")
    env_module = pytest.importorskip(
        "kaggle_environments.envs.kaggriculture.kaggriculture"
    )
    received = []

    def hiring_agent(obs):
        received.append(copy.deepcopy(dict(obs)))
        step = obs["step"]
        hands = obs["farms"][obs["player"]]["hands"]
        return {
            "farmer": ["PICKUP", "WHEAT"] if step < 3 else ["PASS"],
            "hands": [["EAST"]] * len(hands),
            "market": [["HIRE"], ["BUY_PRODUCT", "WHEAT", 3]] if step == 1 else [],
        }

    def starter_agent(obs):
        received.append(copy.deepcopy(dict(obs)))
        return env_module.starter_agent(obs)

    env = kaggle_environments.make(
        "kaggriculture", configuration={"episodeSteps": 100}, debug=True
    )
    env.run([hiring_agent, starter_agent])

    observer = Observer()
    game_states = [observer.observe(obs) for obs in received]

    assert [gs.step for gs in game_states] == [obs["step"] for obs in received]
    assert any(len(gs.player.unit_inventories) == 2 for gs in game_states)
    assert any(gs.player.unit_inventories[0].items for gs in game_states)
    assert any(gs.town.unlocked_shops for gs in game_states)
