"""Unit tests for the complete-turn representation and its simulation."""

import copy
import dataclasses

import pytest

from dimitri.models.farm import Farm
from dimitri.models.game_state import GameState
from dimitri.models.inventory import Inventory
from dimitri.models.market import Market
from dimitri.models.opponent import Opponent
from dimitri.models.player import Player
from dimitri.models.town import Town
from dimitri.planner.action import (
    BUY_LAND,
    BUY_PRODUCT,
    BUY_SEED,
    HIRE,
    MARKET_ACTION_TYPES,
    PLANT,
    SELL,
    Action,
)
from dimitri.planner.simulator import Simulator
from dimitri.planner.turn import Turn


def _make_farm() -> Farm:
    return Farm(
        tiles=[[None, "LOCKED"], [{"type": "WHEAT"}, None]],
        farmer=[0, 0],
        hands=[[1, 1]],
        unlocked_quadrants=["NW"],
        hires_today=1,
    )


def _make_game_state(money=100, shed=None, seeds=None) -> GameState:
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
            prices={"WHEAT": 25, "EGG": 40, "TOMATO": 30},
            inventory={"WHEAT": 10000, "EGG": 9000},
        ),
        town=Town(unlocked_shops=()),
        raw_observation={"day": 3, "hour": 7},
    )


# --- representation ---


def test_turn_can_contain_a_farmer_action():
    plant = Action(PLANT, "WHEAT")

    turn = Turn(farmer=plant)

    assert turn.farmer is plant
    assert turn.hands == ()
    assert turn.market == ()


def test_turn_can_contain_hand_actions():
    first, second = Action(PLANT, "WHEAT"), Action(PLANT, "TOMATO")

    turn = Turn(hands=(first, second))

    assert turn.farmer is None
    assert turn.hands == (first, second)


def test_turn_can_contain_multiple_market_orders():
    orders = (Action(SELL, "EGG", 2), Action(HIRE), Action(BUY_SEED, "WHEAT", 3))

    turn = Turn(market=orders)

    assert turn.market == orders


def test_empty_turn_is_representable():
    turn = Turn()

    assert turn.farmer is None
    assert turn.hands == ()
    assert turn.market == ()
    assert turn.actions() == ()


def test_turn_is_immutable():
    turn = Turn()

    with pytest.raises(dataclasses.FrozenInstanceError):
        turn.farmer = Action(PLANT, "WHEAT")


def test_turn_has_exactly_the_three_api_channels():
    assert {f.name for f in dataclasses.fields(Turn)} == {"farmer", "hands", "market"}


def test_actions_follow_kaggriculture_application_order():
    farmer = Action(PLANT, "WHEAT")
    hand = Action(PLANT, "TOMATO")
    sell, buy = Action(SELL, "EGG"), Action(BUY_PRODUCT, "WHEAT")

    turn = Turn(farmer=farmer, hands=(hand,), market=(sell, buy))

    assert turn.actions() == (farmer, hand, sell, buy)


# --- single-action compatibility ---


@pytest.mark.parametrize("action_type", sorted(MARKET_ACTION_TYPES))
def test_from_action_puts_market_action_in_market(action_type):
    target = None if action_type in (HIRE, BUY_LAND) else "WHEAT"
    action = Action(action_type, target)

    assert Turn.from_action(action) == Turn(market=(action,))


def test_from_action_gives_farm_work_to_farmer():
    action = Action(PLANT, "WHEAT")

    turn = Turn.from_action(action)

    assert turn == Turn(farmer=action)
    assert turn.farmer is action


# --- simulation ---


def test_simulate_turn_applies_every_channel():
    game_state = _make_game_state(money=100)
    turn = Turn(
        farmer=Action(PLANT, "WHEAT"),
        hands=(Action(PLANT, "TOMATO"),),
        market=(Action(SELL, "EGG"), Action(BUY_PRODUCT, "WHEAT", 2)),
    )

    result = Simulator().simulate_turn(game_state, turn)

    assert result.player.seeds == {"WHEAT": 2, "TOMATO": 0}
    # Environment quotes: EGG sells for 110 at inventory 9000; WHEAT buys
    # for 26 at 9999 and 26 at 9998.
    assert result.player.money == 100 + 110 - 26 - 26
    assert result.player.inventory.items == {"WHEAT": 4, "EGG": 0}


def test_simulate_turn_applies_actions_in_order():
    # Buying is only affordable with the proceeds of the earlier sale.
    game_state = _make_game_state(money=0, shed={"EGG": 1})
    turn = Turn(market=(Action(SELL, "EGG"), Action(BUY_PRODUCT, "WHEAT")))

    result = Simulator().simulate_turn(game_state, turn)

    # EGG sells for 110 at inventory 9000; WHEAT buys for 26 at 9999.
    assert result.player.money == 110 - 26
    assert result.player.inventory.items == {"EGG": 0, "WHEAT": 1}


def test_simulate_turn_rejects_a_turn_with_an_invalid_action():
    game_state = _make_game_state(money=0, shed={"EGG": 1})
    turn = Turn(market=(Action(BUY_PRODUCT, "WHEAT"), Action(SELL, "EGG")))

    with pytest.raises(ValueError, match="Cannot afford"):
        Simulator().simulate_turn(game_state, turn)


def test_simulate_single_action_turn_matches_simulate():
    game_state = _make_game_state()
    action = Action(SELL, "WHEAT")

    assert Simulator().simulate_turn(
        game_state, Turn.from_action(action)
    ) == Simulator().simulate(game_state, action)


def test_simulate_empty_turn_returns_unchanged_copy():
    game_state = _make_game_state()

    result = Simulator().simulate_turn(game_state, Turn())

    assert result == game_state
    assert result is not game_state
    assert result.player.seeds is not game_state.player.seeds


def test_simulate_turn_does_not_mutate_original():
    game_state = _make_game_state()
    before = copy.deepcopy(game_state)
    turn = Turn(farmer=Action(PLANT, "WHEAT"), market=(Action(SELL, "EGG"),))

    Simulator().simulate_turn(game_state, turn)

    assert game_state == before
