"""Unit tests for the Planner's candidate action generation."""

import copy
from dataclasses import FrozenInstanceError

import pytest

from dimitri.models.farm import Farm
from dimitri.models.game_state import GameState
from dimitri.models.inventory import Inventory
from dimitri.models.market import Market
from dimitri.models.opponent import Opponent
from dimitri.models.player import Player
from dimitri.planner.action import Action
from dimitri.planner.generator import CandidateGenerator


def _make_farm() -> Farm:
    return Farm(
        tiles=[[None, "LOCKED"]],
        farmer=[0, 0],
        hands=[],
        unlocked_quadrants=["NW"],
        hires_today=0,
    )


def _make_game_state(money=100, shed=None, seeds=None, prices=None) -> GameState:
    return GameState(
        day=0,
        hour=0,
        player=Player(
            player_id=0,
            money=money,
            inventory=Inventory(items={} if shed is None else shed),
            seeds={} if seeds is None else seeds,
            farm=_make_farm(),
        ),
        opponent=Opponent(player_id=1, money=100, farm=_make_farm()),
        market=Market(
            prices={} if prices is None else prices,
            inventory={},
        ),
        raw_observation={"day": 0, "hour": 0},
    )


def _generate(**kwargs) -> tuple[Action, ...]:
    return CandidateGenerator().generate(_make_game_state(**kwargs))


def _of_type(actions, action_type) -> list[Action]:
    return [action for action in actions if action.action_type == action_type]


# --- BUY ---


def test_affordable_items_generate_buy_actions():
    actions = _generate(money=100, prices={"WHEAT": 25, "EGG": 40})

    assert _of_type(actions, "BUY") == [
        Action(action_type="BUY", target="WHEAT", quantity=1),
        Action(action_type="BUY", target="EGG", quantity=1),
    ]


def test_items_more_expensive_than_money_do_not_generate_buy_actions():
    actions = _generate(money=100, prices={"WHEAT": 25, "COW": 101})

    assert [action.target for action in _of_type(actions, "BUY")] == ["WHEAT"]


def test_item_priced_exactly_at_money_generates_buy_action():
    actions = _generate(money=100, prices={"COW": 100})

    assert _of_type(actions, "BUY") == [
        Action(action_type="BUY", target="COW", quantity=1)
    ]


# --- SELL ---


def test_inventory_items_with_positive_quantity_generate_sell_actions():
    actions = _generate(
        money=0,
        shed={"WHEAT": 2, "EGG": 1},
        prices={"WHEAT": 25, "EGG": 40},
    )

    assert _of_type(actions, "SELL") == [
        Action(action_type="SELL", target="WHEAT", quantity=1),
        Action(action_type="SELL", target="EGG", quantity=1),
    ]


def test_inventory_items_with_zero_quantity_do_not_generate_sell_actions():
    actions = _generate(
        money=0,
        shed={"WHEAT": 0, "EGG": 3},
        prices={"WHEAT": 25, "EGG": 40},
    )

    assert [action.target for action in _of_type(actions, "SELL")] == ["EGG"]


def test_inventory_items_without_market_price_do_not_generate_sell_actions():
    actions = _generate(
        money=0,
        shed={"WHEAT": 2, "TRUFFLE": 5},
        prices={"WHEAT": 25},
    )

    assert [action.target for action in _of_type(actions, "SELL")] == ["WHEAT"]


# --- PLANT ---


def test_seeds_with_positive_quantity_generate_plant_actions():
    actions = _generate(seeds={"WHEAT": 5, "TOMATO": 1})

    assert _of_type(actions, "PLANT") == [
        Action(action_type="PLANT", target="WHEAT", quantity=1),
        Action(action_type="PLANT", target="TOMATO", quantity=1),
    ]


def test_seeds_with_zero_quantity_do_not_generate_plant_actions():
    actions = _generate(seeds={"WHEAT": 0, "TOMATO": 2})

    assert [action.target for action in _of_type(actions, "PLANT")] == ["TOMATO"]


# --- Ordering, shape, and purity ---


def _full_state() -> GameState:
    return _make_game_state(
        money=50,
        shed={"EGG": 1, "WHEAT": 3},
        seeds={"TOMATO": 2, "WHEAT": 1},
        prices={"WHEAT": 25, "EGG": 40, "COW": 500},
    )


def test_buy_actions_precede_sell_and_sell_precede_plant():
    types = [action.action_type for action in CandidateGenerator().generate(_full_state())]

    assert types == ["BUY", "BUY", "SELL", "SELL", "PLANT", "PLANT"]


def test_all_buy_actions_appear_before_any_sell_action():
    types = [action.action_type for action in CandidateGenerator().generate(_full_state())]

    assert max(i for i, t in enumerate(types) if t == "BUY") < min(
        i for i, t in enumerate(types) if t == "SELL"
    )


def test_all_sell_actions_appear_before_any_plant_action():
    types = [action.action_type for action in CandidateGenerator().generate(_full_state())]

    assert max(i for i, t in enumerate(types) if t == "SELL") < min(
        i for i, t in enumerate(types) if t == "PLANT"
    )


def test_mapping_order_is_preserved_within_each_category():
    actions = CandidateGenerator().generate(_full_state())

    assert actions == (
        Action(action_type="BUY", target="WHEAT", quantity=1),
        Action(action_type="BUY", target="EGG", quantity=1),
        Action(action_type="SELL", target="EGG", quantity=1),
        Action(action_type="SELL", target="WHEAT", quantity=1),
        Action(action_type="PLANT", target="TOMATO", quantity=1),
        Action(action_type="PLANT", target="WHEAT", quantity=1),
    )


def test_every_generated_action_has_quantity_one():
    actions = _generate(
        money=1000,
        shed={"WHEAT": 9, "EGG": 4},
        seeds={"TOMATO": 7},
        prices={"WHEAT": 25, "EGG": 40},
    )

    assert actions
    assert all(action.quantity == 1 for action in actions)


def test_empty_state_generates_no_actions():
    assert _generate(money=0) == ()


def test_generate_returns_a_tuple():
    assert isinstance(CandidateGenerator().generate(_full_state()), tuple)


def test_generation_is_deterministic():
    game_state = _full_state()
    generator = CandidateGenerator()

    assert generator.generate(game_state) == generator.generate(game_state)
    assert CandidateGenerator().generate(_full_state()) == generator.generate(game_state)


def test_generation_does_not_mutate_game_state():
    game_state = _full_state()
    snapshot = copy.deepcopy(game_state)

    CandidateGenerator().generate(game_state)

    assert game_state == snapshot


def test_action_is_immutable():
    action = Action(action_type="BUY", target="WHEAT", quantity=1)

    with pytest.raises(FrozenInstanceError):
        action.quantity = 2


def test_action_defaults():
    action = Action(action_type="WAIT")

    assert action.target is None
    assert action.quantity == 1
