"""Unit tests for the Planner's single-action state simulator."""

import copy

import pytest

from dimitri.models.farm import Farm
from dimitri.models.game_state import GameState
from dimitri.models.inventory import Inventory
from dimitri.models.market import Market
from dimitri.models.opponent import Opponent
from dimitri.models.player import Player
from dimitri.planner.action import Action
from dimitri.planner.simulator import Simulator


def _make_farm() -> Farm:
    return Farm(
        tiles=[[None, "LOCKED"], [{"type": "WHEAT"}, None]],
        farmer=[0, 0],
        hands=[[1, 1]],
        unlocked_quadrants=["NW"],
        hires_today=1,
    )


def _make_game_state(money=100, shed=None, seeds=None, prices=None) -> GameState:
    return GameState(
        day=3,
        hour=7,
        player=Player(
            player_id=0,
            money=money,
            inventory=Inventory(items={"WHEAT": 2, "EGG": 1} if shed is None else shed),
            seeds={"WHEAT": 3, "TOMATO": 1} if seeds is None else seeds,
            farm=_make_farm(),
        ),
        opponent=Opponent(player_id=1, money=250, farm=_make_farm()),
        market=Market(
            prices={"WHEAT": 25, "EGG": 40, "COW": 500} if prices is None else prices,
            inventory={"WHEAT": 10000, "EGG": 9000},
        ),
        raw_observation={"day": 3, "hour": 7},
    )


def _simulate(game_state, action_type, target, quantity=1) -> GameState:
    return Simulator().simulate(game_state, Action(action_type, target, quantity))


# --- BUY ---


def test_buy_decreases_money_by_current_price():
    result = _simulate(_make_game_state(money=100), "BUY", "WHEAT")

    assert result.player.money == 75


def test_buy_increases_inventory():
    result = _simulate(_make_game_state(), "BUY", "WHEAT")

    assert result.player.inventory.items["WHEAT"] == 3


def test_buy_adds_new_item_to_inventory():
    result = _simulate(_make_game_state(shed={}), "BUY", "EGG")

    assert result.player.inventory.items == {"EGG": 1}


def test_buy_multiple_units_charges_total_cost():
    result = _simulate(_make_game_state(money=100), "BUY", "WHEAT", quantity=3)

    assert result.player.money == 25
    assert result.player.inventory.items["WHEAT"] == 5


def test_buy_does_not_mutate_original_state():
    game_state = _make_game_state()
    snapshot = copy.deepcopy(game_state)

    _simulate(game_state, "BUY", "WHEAT")

    assert game_state == snapshot


def test_buy_unaffordable_item_raises():
    with pytest.raises(ValueError):
        _simulate(_make_game_state(money=100), "BUY", "COW")


def test_buy_unaffordable_total_raises():
    with pytest.raises(ValueError):
        _simulate(_make_game_state(money=100), "BUY", "WHEAT", quantity=5)


def test_buy_unknown_item_raises():
    with pytest.raises(ValueError):
        _simulate(_make_game_state(), "BUY", "TRUFFLE")


def test_buy_missing_target_raises():
    with pytest.raises(ValueError):
        _simulate(_make_game_state(), "BUY", None)


@pytest.mark.parametrize("quantity", [0, -1])
def test_buy_invalid_quantity_raises(quantity):
    with pytest.raises(ValueError):
        _simulate(_make_game_state(), "BUY", "WHEAT", quantity=quantity)


# --- SELL ---


def test_sell_increases_money_by_quantity_times_price():
    result = _simulate(_make_game_state(money=100), "SELL", "WHEAT", quantity=2)

    assert result.player.money == 150


def test_sell_decreases_inventory():
    result = _simulate(_make_game_state(), "SELL", "WHEAT")

    assert result.player.inventory.items["WHEAT"] == 1


def test_sell_does_not_mutate_original_state():
    game_state = _make_game_state()
    snapshot = copy.deepcopy(game_state)

    _simulate(game_state, "SELL", "WHEAT")

    assert game_state == snapshot


def test_sell_more_than_owned_raises():
    with pytest.raises(ValueError):
        _simulate(_make_game_state(), "SELL", "WHEAT", quantity=3)


def test_sell_unowned_item_raises():
    with pytest.raises(ValueError):
        _simulate(_make_game_state(), "SELL", "COW")


def test_sell_unknown_item_raises():
    game_state = _make_game_state(shed={"TRUFFLE": 5})

    with pytest.raises(ValueError):
        _simulate(game_state, "SELL", "TRUFFLE")


def test_sell_missing_target_raises():
    with pytest.raises(ValueError):
        _simulate(_make_game_state(), "SELL", None)


@pytest.mark.parametrize("quantity", [0, -1])
def test_sell_invalid_quantity_raises(quantity):
    with pytest.raises(ValueError):
        _simulate(_make_game_state(), "SELL", "WHEAT", quantity=quantity)


# --- PLANT ---


def test_plant_decreases_seed_count():
    result = _simulate(_make_game_state(), "PLANT", "WHEAT")

    assert result.player.seeds == {"WHEAT": 2, "TOMATO": 1}


def test_plant_changes_only_seeds():
    game_state = _make_game_state()

    result = _simulate(game_state, "PLANT", "WHEAT")

    assert result.player.money == game_state.player.money
    assert result.player.inventory == game_state.player.inventory
    assert result.player.farm == game_state.player.farm


def test_plant_does_not_mutate_original_state():
    game_state = _make_game_state()
    snapshot = copy.deepcopy(game_state)

    _simulate(game_state, "PLANT", "WHEAT")

    assert game_state == snapshot


def test_plant_without_enough_seeds_raises():
    with pytest.raises(ValueError):
        _simulate(_make_game_state(), "PLANT", "TOMATO", quantity=2)


def test_plant_unknown_seed_raises():
    with pytest.raises(ValueError):
        _simulate(_make_game_state(), "PLANT", "MELON")


def test_plant_missing_target_raises():
    with pytest.raises(ValueError):
        _simulate(_make_game_state(), "PLANT", None)


@pytest.mark.parametrize("quantity", [0, -1])
def test_plant_invalid_quantity_raises(quantity):
    with pytest.raises(ValueError):
        _simulate(_make_game_state(), "PLANT", "WHEAT", quantity=quantity)


# --- General ---


@pytest.mark.parametrize("action_type", ["WAIT", "HARVEST", "buy", ""])
def test_unsupported_action_type_raises(action_type):
    with pytest.raises(ValueError):
        _simulate(_make_game_state(), action_type, "WHEAT")


_VALID_ACTIONS = [
    ("BUY", "WHEAT"),
    ("SELL", "EGG"),
    ("PLANT", "TOMATO"),
]


@pytest.mark.parametrize(("action_type", "target"), _VALID_ACTIONS)
def test_simulation_returns_new_game_state(action_type, target):
    game_state = _make_game_state()

    result = _simulate(game_state, action_type, target)

    assert isinstance(result, GameState)
    assert result is not game_state
    assert result.player is not game_state.player


@pytest.mark.parametrize(("action_type", "target"), _VALID_ACTIONS)
def test_simulation_preserves_day_and_hour(action_type, target):
    result = _simulate(_make_game_state(), action_type, target)

    assert (result.day, result.hour) == (3, 7)


@pytest.mark.parametrize(("action_type", "target"), _VALID_ACTIONS)
def test_simulation_preserves_market_prices(action_type, target):
    game_state = _make_game_state()

    result = _simulate(game_state, action_type, target)

    assert result.market.prices == game_state.market.prices


@pytest.mark.parametrize(("action_type", "target"), _VALID_ACTIONS)
def test_simulation_preserves_market_inventory(action_type, target):
    game_state = _make_game_state()

    result = _simulate(game_state, action_type, target)

    assert result.market.inventory == game_state.market.inventory


@pytest.mark.parametrize(("action_type", "target"), _VALID_ACTIONS)
def test_simulation_preserves_opponent(action_type, target):
    game_state = _make_game_state()

    result = _simulate(game_state, action_type, target)

    assert result.opponent == game_state.opponent


@pytest.mark.parametrize(("action_type", "target"), _VALID_ACTIONS)
def test_simulation_preserves_farm(action_type, target):
    game_state = _make_game_state()

    result = _simulate(game_state, action_type, target)

    assert result.player.farm == game_state.player.farm


@pytest.mark.parametrize(("action_type", "target"), _VALID_ACTIONS)
def test_mutating_simulated_state_does_not_mutate_original(action_type, target):
    game_state = _make_game_state()
    snapshot = copy.deepcopy(game_state)

    result = _simulate(game_state, action_type, target)
    result.player.inventory.items["NEW"] = 99
    result.player.seeds["NEW"] = 99
    result.player.farm.tiles[0][0] = {"type": "WEED"}
    result.player.farm.tiles.append([None])
    result.player.farm.hands.append([0, 1])
    result.player.farm.hands[0][0] = 9
    result.player.farm.unlocked_quadrants.append("SE")
    result.player.farm.farmer[0] = 9
    result.market.prices["WHEAT"] = 1
    result.market.inventory["WHEAT"] = 1
    result.opponent.farm.tiles[0][0] = {"type": "WEED"}
    result.opponent.farm.hands.append([0, 1])
    result.opponent.farm.unlocked_quadrants.append("SE")
    result.raw_observation["day"] = 99

    assert game_state == snapshot
