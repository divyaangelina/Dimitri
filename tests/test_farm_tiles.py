"""Unit tests for parsing farm tile contents into immutable tile models.

Raw tile dicts in these tests mirror the structures the Kaggriculture
environment writes (``_new_plant``, ``_new_animal``, ``BUILD_COOP`` /
``BUILD_PASTURE``, weed spawning). One test also builds tiles with the
installed environment's own constructors so that drift in the real
schema is caught here.
"""

import copy
import json
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest

from dimitri.analyst.analyst import Analyst
from dimitri.models.farm import Farm
from dimitri.models.tile import AnimalTile, PlantTile, StructureTile, WeedTile
from dimitri.observer.observer import Observer
from dimitri.observer.parser import ParseError, parse

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"

PLANT_DICT = {
    "kind": "PLANT",
    "crop": "WHEAT",
    "planted_day": 3,
    "watered_today": True,
    "consecutive_unwatered": 0,
    "yield_units": 2,
    "max_lifespan_step": 80,
    "fertilized_until_day": 5,
}

ANIMAL_DICT = {
    "kind": "PASTURE",
    "animal": "COW",
    "placed_day": 2,
    "yield_units": 1,
    "consecutive_unfed": 1,
    "fed_today": False,
    "cared_today": True,
    "fertilizer_available": True,
    "pending_care_bonus": 2,
}


def _load_sample_observation() -> dict:
    with SAMPLE_OBSERVATION_PATH.open() as f:
        return json.load(f)


def _observation_with_tiles(tiles, *, farm_index=0) -> dict:
    observation = _load_sample_observation()
    observation["farms"][farm_index]["tiles"] = tiles
    return observation


def _parse_single_tile(raw_tile):
    return parse(_observation_with_tiles([[raw_tile]])).player.farm.tiles[0][0]


# --- empty and locked tiles ---------------------------------------------


def test_empty_unlocked_tile_parses_to_none():
    assert _parse_single_tile(None) is None


def test_locked_tile_parses_to_locked():
    assert _parse_single_tile("LOCKED") == "LOCKED"


# --- plant tiles --------------------------------------------------------


def test_plant_tile_parses_to_plant_tile_with_all_observed_fields():
    tile = _parse_single_tile(PLANT_DICT)

    assert tile == PlantTile(
        crop="WHEAT",
        planted_day=3,
        watered_today=True,
        consecutive_unwatered=0,
        yield_units=2,
        max_lifespan_step=80,
        fertilized_until_day=5,
    )


def test_plant_tile_fields_match_environment_keys():
    expected = set(PLANT_DICT) - {"kind"}
    assert {f.name for f in fields(PlantTile)} == expected


# --- animal and structure tiles ----------------------------------------


def test_animal_tile_parses_to_animal_tile_with_all_observed_fields():
    tile = _parse_single_tile(ANIMAL_DICT)

    assert tile == AnimalTile(
        structure="PASTURE",
        animal="COW",
        placed_day=2,
        yield_units=1,
        consecutive_unfed=1,
        fed_today=False,
        cared_today=True,
        fertilizer_available=True,
        pending_care_bonus=2,
    )


def test_animal_tile_fields_match_environment_keys():
    # The environment's "kind" key is exposed as "structure".
    expected = (set(ANIMAL_DICT) - {"kind"}) | {"structure"}
    assert {f.name for f in fields(AnimalTile)} == expected


def test_goose_in_coop_parses_to_animal_tile():
    raw = dict(ANIMAL_DICT, kind="COOP", animal="GOOSE")

    tile = _parse_single_tile(raw)

    assert isinstance(tile, AnimalTile)
    assert tile.structure == "COOP"
    assert tile.animal == "GOOSE"


@pytest.mark.parametrize("kind", ["COOP", "PASTURE"])
def test_empty_structure_parses_to_structure_tile(kind):
    assert _parse_single_tile({"kind": kind}) == StructureTile(structure=kind)


def test_weed_tile_parses_to_weed_tile():
    assert _parse_single_tile({"kind": "WEED"}) == WeedTile()


def test_tiles_built_by_real_environment_parse():
    """Tile dicts produced by the installed environment's own constructors parse."""
    env = pytest.importorskip("kaggle_environments.envs.kaggriculture.kaggriculture")
    raw_plant = env._new_plant("WHEAT", 3, 10)
    raw_animal = env._new_animal("GOOSE", 1)

    tiles = parse(_observation_with_tiles([[raw_plant, raw_animal]])).player.farm.tiles

    assert tiles[0][0] == PlantTile(
        **{k: v for k, v in raw_plant.items() if k != "kind"}
    )
    assert tiles[0][1] == AnimalTile(
        structure=raw_animal["kind"],
        **{k: v for k, v in raw_animal.items() if k != "kind"},
    )


# --- grid shape and opponent -------------------------------------------


def test_grid_shape_and_positions_are_preserved():
    raw_tiles = [
        [None, "LOCKED", {"kind": "WEED"}],
        [PLANT_DICT, ANIMAL_DICT, {"kind": "COOP"}],
    ]

    tiles = parse(_observation_with_tiles(raw_tiles)).player.farm.tiles

    assert [len(row) for row in tiles] == [3, 3]
    assert tiles[0][0] is None
    assert tiles[0][1] == "LOCKED"
    assert isinstance(tiles[0][2], WeedTile)
    assert isinstance(tiles[1][0], PlantTile)
    assert isinstance(tiles[1][1], AnimalTile)
    assert isinstance(tiles[1][2], StructureTile)


def test_opponent_tiles_are_parsed_into_models():
    observation = _observation_with_tiles([[PLANT_DICT]], farm_index=1)

    assert isinstance(parse(observation).opponent.farm.tiles[0][0], PlantTile)


def test_parsing_does_not_mutate_observation():
    observation = _observation_with_tiles([[PLANT_DICT, ANIMAL_DICT, None]])
    snapshot = copy.deepcopy(observation)

    parse(observation)

    assert observation == snapshot


# --- immutability -------------------------------------------------------


@pytest.mark.parametrize("raw", [PLANT_DICT, ANIMAL_DICT])
def test_tile_models_are_frozen(raw):
    tile = _parse_single_tile(raw)

    with pytest.raises(FrozenInstanceError):
        tile.yield_units = 99


def test_structure_tile_is_frozen():
    with pytest.raises(FrozenInstanceError):
        StructureTile(structure="COOP").structure = "PASTURE"


def test_parsed_tile_grid_is_immutable():
    tiles = parse(_observation_with_tiles([[None, PLANT_DICT]])).player.farm.tiles

    assert isinstance(tiles, tuple)
    assert all(isinstance(row, tuple) for row in tiles)
    with pytest.raises(TypeError):
        tiles[0][0] = "LOCKED"


def test_parsed_tiles_do_not_alias_observation():
    observation = _observation_with_tiles([[dict(PLANT_DICT)]])
    game_state = parse(observation)

    observation["farms"][0]["tiles"][0][0]["yield_units"] = 99

    assert game_state.player.farm.tiles[0][0].yield_units == 2


# --- malformed and unknown tiles ---------------------------------------


def test_unknown_tile_kind_raises_parse_error():
    with pytest.raises(ParseError, match="Unknown tile kind 'BARN'"):
        _parse_single_tile({"kind": "BARN"})


def test_tile_without_kind_raises_parse_error():
    with pytest.raises(ParseError, match="Missing 'kind'"):
        _parse_single_tile({"crop": "WHEAT"})


@pytest.mark.parametrize("raw", ["EMPTY", 0, ["PLANT"]])
def test_unexpected_tile_value_raises_parse_error(raw):
    with pytest.raises(ParseError):
        _parse_single_tile(raw)


@pytest.mark.parametrize("missing", sorted(set(PLANT_DICT) - {"kind"}))
def test_plant_missing_field_raises_parse_error(missing):
    raw = {k: v for k, v in PLANT_DICT.items() if k != missing}

    with pytest.raises(ParseError, match=f"Missing '{missing}'"):
        _parse_single_tile(raw)


@pytest.mark.parametrize("missing", sorted(set(ANIMAL_DICT) - {"kind", "animal"}))
def test_animal_missing_field_raises_parse_error(missing):
    raw = {k: v for k, v in ANIMAL_DICT.items() if k != missing}

    with pytest.raises(ParseError, match=f"Missing '{missing}'"):
        _parse_single_tile(raw)


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        (dict(PLANT_DICT, yield_units="2"), "yield_units"),
        (dict(PLANT_DICT, planted_day=True), "planted_day"),
        (dict(PLANT_DICT, watered_today=1), "watered_today"),
        (dict(ANIMAL_DICT, fed_today=None), "fed_today"),
        (dict(ANIMAL_DICT, animal=3), "animal"),
    ],
)
def test_wrongly_typed_field_raises_parse_error(raw, key):
    with pytest.raises(ParseError, match=f"'{key}'"):
        _parse_single_tile(raw)


def test_non_sequence_tile_row_raises_parse_error():
    with pytest.raises(ParseError, match="Expected a sequence"):
        parse(_observation_with_tiles([None]))


# --- existing Farm/GameState behavior ----------------------------------


def test_sample_observation_still_parses_and_validates():
    observation = _load_sample_observation()

    game_state = Observer().observe(observation)

    assert isinstance(game_state.player.farm, Farm)
    raw_tiles = observation["farms"][game_state.player.player_id]["tiles"]
    assert [list(row) for row in game_state.player.farm.tiles] == raw_tiles


def test_analyst_counts_parsed_tile_models_as_occupied():
    raw_tiles = [
        [None, "LOCKED", {"kind": "WEED"}],
        [PLANT_DICT, ANIMAL_DICT, {"kind": "COOP"}],
    ]

    analysis = Analyst().analyze(parse(_observation_with_tiles(raw_tiles)))

    assert analysis.occupied_tiles == 4
    assert analysis.empty_tiles == 1
    assert analysis.locked_tiles == 1
    assert analysis.unlocked_tiles == 5
