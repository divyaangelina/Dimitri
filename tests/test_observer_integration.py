"""Integration test for the observation pipeline: Observer -> Parser -> GameState -> Validator.

This test exercises the real Parser, Validator, and Observer together
against a captured Kaggriculture observation, rather than re-testing
either component's internal logic in isolation (that is covered by
their own unit tests). It confirms that the pipeline as a whole
produces a correct, validated GameState from a real observation, and
that it propagates upstream errors rather than swallowing them.
"""

import copy
import json
from pathlib import Path

import pytest

from dimitri.models.farm import Farm
from dimitri.models.game_state import GameState
from dimitri.models.inventory import Inventory
from dimitri.models.opponent import Opponent
from dimitri.observer.observer import Observer
from dimitri.observer.parser import ParseError
from dimitri.observer.validator import ValidationError

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"


def _load_sample_observation() -> dict:
    """Load the real captured observation used by this test."""
    with SAMPLE_OBSERVATION_PATH.open() as f:
        return json.load(f)


def test_observe_returns_validated_game_state():
    """A valid sample observation passes through Observer and yields a GameState."""
    observation = _load_sample_observation()
    observer = Observer()

    game_state = observer.observe(observation)

    assert isinstance(game_state, GameState)


def test_observe_produces_expected_values():
    """The GameState returned by Observer reflects the sample observation's values."""
    observation = _load_sample_observation()
    observer = Observer()

    game_state = observer.observe(observation)

    assert game_state.day == 0
    assert game_state.player.money == 3000
    assert game_state.player.inventory.items == observation["private"]["shed"]
    assert game_state.market.prices["WHEAT"] == 25


def test_observe_produces_correct_nested_hierarchy():
    """Player.inventory exists and is an Inventory (GameState has no standalone inventory field)."""
    observation = _load_sample_observation()
    observer = Observer()

    game_state = observer.observe(observation)

    assert isinstance(game_state.player.inventory, Inventory)
    assert not hasattr(game_state, "inventory")


def test_observe_produces_hour_and_opponent():
    """GameState carries hour and an Opponent alongside Player, per the current hierarchy."""
    observation = _load_sample_observation()
    observer = Observer()

    game_state = observer.observe(observation)

    assert game_state.hour == observation["hour"]
    assert isinstance(game_state.opponent, Opponent)
    assert game_state.opponent.player_id != game_state.player.player_id
    assert not hasattr(game_state.opponent, "inventory")


def test_observe_produces_player_seeds_and_farm():
    """Player carries seeds and a Farm, matching the private.seeds and public farms[player] data."""
    observation = _load_sample_observation()
    observer = Observer()

    game_state = observer.observe(observation)

    assert game_state.player.seeds == observation["private"]["seeds"]
    assert isinstance(game_state.player.farm, Farm)
    assert isinstance(game_state.opponent.farm, Farm)


def test_observe_produces_market_inventory():
    """Market carries the shared market's supply alongside its prices."""
    observation = _load_sample_observation()
    observer = Observer()

    game_state = observer.observe(observation)

    assert game_state.market.inventory == observation["market"]["inventory"]


def test_observe_does_not_mutate_the_observation():
    """The raw observation dict is left unchanged after passing through Observer."""
    observation = _load_sample_observation()
    observation_before = copy.deepcopy(observation)
    observer = Observer()

    observer.observe(observation)

    assert observation == observation_before


def test_observe_propagates_parse_error():
    """An observation the Parser cannot parse causes ParseError to propagate through Observer."""
    invalid_observation = {"player": 0, "day": 0}  # missing 'farms', 'private', 'market', 'hour'
    observer = Observer()

    with pytest.raises(ParseError):
        observer.observe(invalid_observation)


def test_observe_propagates_validation_error():
    """An observation that parses but fails validation causes ValidationError to propagate."""
    observation = _load_sample_observation()
    observation["day"] = "not-an-int"  # parses fine, but fails GameState.day type check
    observer = Observer()

    with pytest.raises(ValidationError):
        observer.observe(observation)
