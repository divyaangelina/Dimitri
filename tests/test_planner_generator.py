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
from dimitri.models.town import Town
from dimitri.planner.action import MARKET_ACTION_TYPES, Action
from dimitri.planner.generator import CandidateGenerator


def _make_farm() -> Farm:
    return Farm(
        tiles=[[None, "LOCKED"]],
        farmer=[0, 0],
        hands=[],
        unlocked_quadrants=["NW"],
        hires_today=0,
    )


def _make_game_state(
    money=100, shed=None, seeds=None, prices=None, market_inventory=None
) -> GameState:
    prices = {} if prices is None else prices
    return GameState(
        step=0,
        day=0,
        hour=0,
        player=Player(
            player_id=0,
            money=money,
            inventory=Inventory(items={} if shed is None else shed),
            seeds={} if seeds is None else seeds,
            farm=_make_farm(),
            unit_inventories=(Inventory(items={}),),
        ),
        opponent=Opponent(player_id=1, money=100, farm=_make_farm()),
        market=Market(
            prices=prices,
            # Every priced item defaults to the environment's starting inventory.
            inventory=(
                {item: 10000 for item in prices}
                if market_inventory is None
                else market_inventory
            ),
        ),
        town=Town(unlocked_shops=()),
        raw_observation={"day": 0, "hour": 0},
    )


def _generate(**kwargs) -> tuple[Action, ...]:
    return CandidateGenerator().generate(_make_game_state(**kwargs))


def _of_type(actions, action_type) -> list[Action]:
    return [action for action in actions if action.action_type == action_type]


# --- BUY_PRODUCT ---


def test_affordable_buyable_products_generate_buy_product_actions():
    actions = _generate(money=200, prices={"WHEAT": 25, "EGG": 50, "FERTILIZER": 100})

    assert _of_type(actions, "BUY_PRODUCT") == [
        Action(action_type="BUY_PRODUCT", target="WHEAT", quantity=1),
        Action(action_type="BUY_PRODUCT", target="FERTILIZER", quantity=1),
    ]


@pytest.mark.parametrize("item", ["EGG", "MILK", "CARROT", "COW", "GOOSE"])
def test_products_the_environment_does_not_sell_are_not_bought(item):
    actions = _generate(money=10_000, prices={item: 1})

    assert _of_type(actions, "BUY_PRODUCT") == []


def test_affordability_uses_the_environment_buy_quote_not_the_displayed_price():
    # At the starting inventory WHEAT displays 25 but one unit costs 26.
    assert _of_type(_generate(money=25, prices={"WHEAT": 25}), "BUY_PRODUCT") == []
    assert _of_type(_generate(money=26, prices={"WHEAT": 25}), "BUY_PRODUCT") == [
        Action(action_type="BUY_PRODUCT", target="WHEAT", quantity=1)
    ]


def test_full_shed_generates_no_buy_product_actions():
    actions = _generate(money=10_000, shed={"EGG": 60, "GOOSE": 40}, prices={"WHEAT": 25})

    assert _of_type(actions, "BUY_PRODUCT") == []


def test_buyable_product_without_market_inventory_is_not_bought():
    actions = _generate(money=10_000, prices={"WHEAT": 25}, market_inventory={})

    assert _of_type(actions, "BUY_PRODUCT") == []


# --- SELL ---


def test_inventory_items_with_positive_quantity_generate_sell_actions():
    actions = _generate(
        money=0,
        shed={"WHEAT": 2, "EGG": 1},
        prices={"WHEAT": 25, "EGG": 50},
    )

    assert _of_type(actions, "SELL") == [
        Action(action_type="SELL", target="WHEAT", quantity=1),
        Action(action_type="SELL", target="EGG", quantity=1),
    ]


def test_inventory_items_with_zero_quantity_do_not_generate_sell_actions():
    actions = _generate(
        money=0,
        shed={"WHEAT": 0, "EGG": 3},
        prices={"WHEAT": 25, "EGG": 50},
    )

    assert [action.target for action in _of_type(actions, "SELL")] == ["EGG"]


def test_shed_items_that_are_not_market_products_do_not_generate_sell_actions():
    actions = _generate(
        money=0,
        shed={"WHEAT": 2, "GOOSE": 1, "TRUFFLE": 5},
        prices={"WHEAT": 25, "GOOSE": 300, "TRUFFLE": 9},
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
        money=150,
        shed={"EGG": 1, "WHEAT": 3},
        seeds={"TOMATO": 2, "WHEAT": 1},
        prices={"FERTILIZER": 100, "WHEAT": 25, "EGG": 50, "COW": 400},
    )


def test_buy_product_actions_precede_sell_and_sell_precede_plant():
    types = [action.action_type for action in CandidateGenerator().generate(_full_state())]

    assert types == [
        *["BUY_PRODUCT"] * 2,
        *["BUY_SEED"] * 5,
        *["SELL"] * 2,
        *["PLANT"] * 2,
    ]


def test_all_buy_product_actions_appear_before_any_sell_action():
    types = [action.action_type for action in CandidateGenerator().generate(_full_state())]

    assert max(i for i, t in enumerate(types) if t == "BUY_PRODUCT") < min(
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
        Action(action_type="BUY_PRODUCT", target="FERTILIZER", quantity=1),
        Action(action_type="BUY_PRODUCT", target="WHEAT", quantity=1),
        Action(action_type="BUY_SEED", target="WHEAT", quantity=1),
        Action(action_type="BUY_SEED", target="CARROT", quantity=1),
        Action(action_type="BUY_SEED", target="TOMATO", quantity=1),
        Action(action_type="BUY_SEED", target="STRAWBERRY", quantity=1),
        Action(action_type="BUY_SEED", target="MELON", quantity=1),
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


def test_only_modelled_action_types_are_generated():
    types = {action.action_type for action in CandidateGenerator().generate(_full_state())}

    assert types == {"BUY_PRODUCT", "BUY_SEED", "SELL", "PLANT"}


def test_generic_buy_is_never_generated():
    actions = _generate(
        money=1000,
        shed={"WHEAT": 1},
        seeds={"WHEAT": 1},
        prices={"WHEAT": 25, "FERTILIZER": 100},
    )

    assert "BUY" not in {action.action_type for action in actions}


def test_market_action_types_match_kaggriculture_api():
    assert MARKET_ACTION_TYPES == {
        "BUY_SEED",
        "BUY_ANIMAL",
        "BUY_PRODUCT",
        "SELL",
        "HIRE",
        "BUY_LAND",
    }


def test_plant_is_not_a_market_action():
    assert "PLANT" not in MARKET_ACTION_TYPES


def test_action_is_immutable():
    action = Action(action_type="BUY_PRODUCT", target="WHEAT", quantity=1)

    with pytest.raises(FrozenInstanceError):
        action.quantity = 2


def test_action_defaults():
    action = Action(action_type="WAIT")

    assert action.target is None
    assert action.quantity == 1
