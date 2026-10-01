"""Unit tests for the Planner's single-action state simulator."""

import copy
from dataclasses import replace

import pytest

from dimitri.models.farm import Farm
from dimitri.models.game_state import GameState
from dimitri.models.inventory import Inventory
from dimitri.models.market import Market
from dimitri.models.opponent import Opponent
from dimitri.models.player import Player
from dimitri.models.town import Town
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
        step=79,
        day=3,
        hour=7,
        player=Player(
            player_id=0,
            money=money,
            inventory=Inventory(items={"WHEAT": 2, "EGG": 1} if shed is None else shed),
            seeds={"WHEAT": 3, "TOMATO": 1} if seeds is None else seeds,
            farm=_make_farm(),
            unit_inventories=(Inventory(items={}),),
        ),
        opponent=Opponent(player_id=1, money=250, farm=_make_farm()),
        market=Market(
            prices={"WHEAT": 25, "EGG": 40, "COW": 500} if prices is None else prices,
            inventory={"WHEAT": 10000, "EGG": 9000},
        ),
        town=Town(unlocked_shops=()),
        raw_observation={"day": 3, "hour": 7},
    )


def _simulate(game_state, action_type, target, quantity=1) -> GameState:
    return Simulator().simulate(game_state, Action(action_type, target, quantity))


# --- BUY_PRODUCT ---


def test_buy_product_decreases_money_by_environment_buy_quote():
    # The environment quotes a purchase at the post-buy inventory (9999): 26, not 25.
    result = _simulate(_make_game_state(money=100), "BUY_PRODUCT", "WHEAT")

    assert result.player.money == 74


def test_buy_product_increases_inventory():
    result = _simulate(_make_game_state(), "BUY_PRODUCT", "WHEAT")

    assert result.player.inventory.items["WHEAT"] == 3


def test_buy_product_adds_new_item_to_inventory():
    result = _simulate(_make_game_state(shed={}), "BUY_PRODUCT", "WHEAT")

    assert result.player.inventory.items == {"WHEAT": 1}


def test_buy_product_multiple_units_are_priced_one_at_a_time():
    # Quotes at inventory 9999, 9998, 9997: 26, 26, 27.
    result = _simulate(_make_game_state(money=100), "BUY_PRODUCT", "WHEAT", quantity=3)

    assert result.player.money == 100 - 26 - 26 - 27
    assert result.player.inventory.items["WHEAT"] == 5


def test_buy_product_does_not_mutate_original_state():
    game_state = _make_game_state()
    snapshot = copy.deepcopy(game_state)

    _simulate(game_state, "BUY_PRODUCT", "WHEAT")

    assert game_state == snapshot


def test_buy_product_unaffordable_item_raises():
    with pytest.raises(ValueError):
        _simulate(_make_game_state(money=100), "BUY_PRODUCT", "COW")


def test_buy_product_stops_when_money_runs_out():
    # 3 units cost 79; the 4th (27) is unaffordable with 21 left, so the order stops.
    result = _simulate(_make_game_state(money=100), "BUY_PRODUCT", "WHEAT", quantity=5)

    assert result.player.money == 21
    assert result.player.inventory.items["WHEAT"] == 5


def test_buy_product_unknown_item_raises():
    with pytest.raises(ValueError):
        _simulate(_make_game_state(), "BUY_PRODUCT", "TRUFFLE")


def test_buy_product_missing_target_raises():
    with pytest.raises(ValueError):
        _simulate(_make_game_state(), "BUY_PRODUCT", None)


@pytest.mark.parametrize("quantity", [0, -1])
def test_buy_product_invalid_quantity_raises(quantity):
    with pytest.raises(ValueError):
        _simulate(_make_game_state(), "BUY_PRODUCT", "WHEAT", quantity=quantity)


# --- SELL ---


def test_sell_multiple_units_are_priced_one_at_a_time():
    # Quotes at inventory 10000, 10001: 25, 24.
    result = _simulate(_make_game_state(money=100), "SELL", "WHEAT", quantity=2)

    assert result.player.money == 100 + 25 + 24


def test_sell_decreases_inventory():
    result = _simulate(_make_game_state(), "SELL", "WHEAT")

    assert result.player.inventory.items["WHEAT"] == 1


def test_sell_does_not_mutate_original_state():
    game_state = _make_game_state()
    snapshot = copy.deepcopy(game_state)

    _simulate(game_state, "SELL", "WHEAT")

    assert game_state == snapshot


def test_sell_more_than_owned_stops_when_the_shed_runs_out():
    result = _simulate(_make_game_state(money=100), "SELL", "WHEAT", quantity=3)

    assert result.player.inventory.items["WHEAT"] == 0
    assert result.player.money == 100 + 25 + 24


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


def test_plant_changes_only_seeds_and_the_farmer_tile():
    game_state = _make_game_state()

    result = _simulate(game_state, "PLANT", "WHEAT")

    assert result.player.money == game_state.player.money
    assert result.player.inventory == game_state.player.inventory
    assert result.player.unit_inventories == game_state.player.unit_inventories
    assert result.player.farm.tiles[0][0] != game_state.player.farm.tiles[0][0]
    assert replace(result.player.farm, tiles=None) == replace(
        game_state.player.farm, tiles=None
    )


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


@pytest.mark.parametrize(
    "action_type", ["WAIT", "HARVEST", "BUY", "buy", "buy_product", ""]
)
def test_unsupported_action_type_raises(action_type):
    with pytest.raises(ValueError):
        _simulate(_make_game_state(), action_type, "WHEAT")


@pytest.mark.parametrize("action_type", ["BUY_ANIMAL", "HIRE", "BUY_LAND"])
def test_market_actions_without_modelled_costs_are_unsupported(action_type):
    with pytest.raises(ValueError, match="Unsupported action type"):
        _simulate(_make_game_state(), action_type, "WHEAT")


_VALID_ACTIONS = [
    ("BUY_PRODUCT", "WHEAT"),
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


@pytest.mark.parametrize(("action_type", "target"), _VALID_ACTIONS[2:])
def test_plant_preserves_market_prices(action_type, target):
    game_state = _make_game_state()

    result = _simulate(game_state, action_type, target)

    assert result.market.prices == game_state.market.prices


@pytest.mark.parametrize(("action_type", "target"), _VALID_ACTIONS[2:])
def test_plant_preserves_market_inventory(action_type, target):
    game_state = _make_game_state()

    result = _simulate(game_state, action_type, target)

    assert result.market.inventory == game_state.market.inventory


@pytest.mark.parametrize(("action_type", "target"), _VALID_ACTIONS)
def test_simulation_preserves_opponent(action_type, target):
    game_state = _make_game_state()

    result = _simulate(game_state, action_type, target)

    assert result.opponent == game_state.opponent


@pytest.mark.parametrize(("action_type", "target"), _VALID_ACTIONS[:2])
def test_market_simulation_preserves_farm(action_type, target):
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
    if action_type != "PLANT":  # PLANT rebuilds the grid as immutable tuples.
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
