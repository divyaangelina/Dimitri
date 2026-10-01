"""Unit tests for the Operator's conversion to the Kaggriculture action format."""

import pytest

from dimitri.executive.decision import Decision
from dimitri.operator.operator import Operator
from dimitri.planner.action import (
    BUY_ANIMAL,
    BUY_LAND,
    BUY_PRODUCT,
    BUY_SEED,
    HIRE,
    MARKET_ACTION_TYPES,
    PLANT,
    SELL,
    Action,
)
from dimitri.planner.turn import Turn


@pytest.fixture
def operator() -> Operator:
    return Operator()


# --- farmer and hand actions ---


def test_farmer_plant_is_written_as_single_op(operator):
    result = operator.compose(farmer=Action(PLANT, "WHEAT"))

    assert result["farmer"] == ["PLANT", "WHEAT"]


def test_farmer_without_action_passes(operator):
    assert operator.compose()["farmer"] == ["PASS"]


def test_hand_actions_are_written_as_list_of_ops_in_order(operator):
    result = operator.compose(hands=[Action(PLANT, "WHEAT"), Action(PLANT, "CARROT")])

    assert result["hands"] == [["PLANT", "WHEAT"], ["PLANT", "CARROT"]]


def test_hand_actions_do_not_leak_into_farmer_or_market(operator):
    result = operator.compose(hands=[Action(PLANT, "WHEAT")])

    assert result["farmer"] == ["PASS"]
    assert result["market"] == []


# --- market actions ---


@pytest.mark.parametrize(
    "action, expected",
    [
        (Action(BUY_SEED, "WHEAT", 3), ["BUY_SEED", "WHEAT", 3]),
        (Action(BUY_ANIMAL, "CHICKEN", 1), ["BUY_ANIMAL", "CHICKEN", 1]),
        (Action(BUY_PRODUCT, "FERTILIZER", 2), ["BUY_PRODUCT", "FERTILIZER", 2]),
        (Action(SELL, "EGG", 5), ["SELL", "EGG", 5]),
        (Action(HIRE), ["HIRE"]),
        (Action(BUY_LAND), ["BUY_LAND"]),
    ],
)
def test_market_action_is_written_as_market_order(operator, action, expected):
    assert operator.to_market_order(action) == expected


def test_every_market_action_type_is_supported(operator):
    for action_type in MARKET_ACTION_TYPES:
        target = None if action_type in (HIRE, BUY_LAND) else "WHEAT"
        order = operator.to_market_order(Action(action_type, target))
        assert order[0] == action_type


def test_market_orders_preserve_submission_order(operator):
    result = operator.compose(
        market=[Action(SELL, "WHEAT", 2), Action(HIRE), Action(BUY_SEED, "WHEAT", 1)]
    )

    assert result["market"] == [["SELL", "WHEAT", 2], ["HIRE"], ["BUY_SEED", "WHEAT", 1]]


# --- complete action dict ---


def test_compose_produces_complete_action_dict(operator):
    result = operator.compose(
        farmer=Action(PLANT, "WHEAT"),
        hands=[Action(PLANT, "CARROT")],
        market=[Action(BUY_SEED, "WHEAT", 2), Action(BUY_LAND)],
    )

    assert result == {
        "farmer": ["PLANT", "WHEAT"],
        "hands": [["PLANT", "CARROT"]],
        "market": [["BUY_SEED", "WHEAT", 2], ["BUY_LAND"]],
    }


def test_compose_with_nothing_is_an_idle_turn(operator):
    assert operator.compose() == {"farmer": ["PASS"], "hands": [], "market": []}


def test_execute_routes_market_action_to_market(operator):
    assert operator.execute(Decision(Turn.from_action(Action(SELL, "WHEAT", 4)))) == {
        "farmer": ["PASS"],
        "hands": [],
        "market": [["SELL", "WHEAT", 4]],
    }


def test_execute_routes_farm_work_to_farmer(operator):
    assert operator.execute(Decision(Turn.from_action(Action(PLANT, "TOMATO")))) == {
        "farmer": ["PLANT", "TOMATO"],
        "hands": [],
        "market": [],
    }


def test_execute_does_not_mutate_action(operator):
    action = Action(BUY_PRODUCT, "WHEAT", 2)

    operator.execute(Decision(Turn.from_action(action)))

    assert action == Action(BUY_PRODUCT, "WHEAT", 2)


def test_execute_rejects_undecided_action(operator):
    with pytest.raises(TypeError, match="only a Decision"):
        operator.execute(Action(SELL, "WHEAT", 4))


def test_execute_writes_every_channel_of_a_complete_turn(operator):
    turn = Turn(
        farmer=Action(PLANT, "WHEAT"),
        hands=(Action(PLANT, "CARROT"), Action(PLANT, "TOMATO")),
        market=(Action(SELL, "EGG", 3), Action(HIRE), Action(BUY_SEED, "WHEAT", 2)),
    )

    assert operator.execute(Decision(turn)) == {
        "farmer": ["PLANT", "WHEAT"],
        "hands": [["PLANT", "CARROT"], ["PLANT", "TOMATO"]],
        "market": [["SELL", "EGG", 3], ["HIRE"], ["BUY_SEED", "WHEAT", 2]],
    }


def test_execute_matches_compose_for_the_same_channels(operator):
    turn = Turn(hands=(Action(PLANT, "WHEAT"),), market=(Action(SELL, "EGG", 1),))

    assert operator.execute(Decision(turn)) == operator.compose(
        hands=turn.hands, market=turn.market
    )


def test_execute_empty_turn_is_an_idle_turn(operator):
    assert operator.execute(Decision(Turn())) == {
        "farmer": ["PASS"],
        "hands": [],
        "market": [],
    }


def test_execute_rejects_undecided_turn(operator):
    with pytest.raises(TypeError, match="only a Decision"):
        operator.execute(Turn())


def test_execute_rejects_market_action_given_to_farmer(operator):
    with pytest.raises(ValueError):
        operator.execute(Decision(Turn(farmer=Action(SELL, "WHEAT", 1))))


def test_execute_rejects_farm_work_in_market(operator):
    with pytest.raises(ValueError):
        operator.execute(Decision(Turn(market=(Action(PLANT, "WHEAT"),))))


# --- rejection of malformed or unsupported actions ---


@pytest.mark.parametrize("action_type", ["BUY", "FLY", "", "sell"])
def test_execute_rejects_unknown_action_type(operator, action_type):
    with pytest.raises(ValueError):
        operator.execute(Decision(Turn.from_action(Action(action_type, "WHEAT"))))


@pytest.mark.parametrize("action_type", sorted(MARKET_ACTION_TYPES))
def test_market_action_cannot_be_given_to_farmer_or_hand(operator, action_type):
    target = None if action_type in (HIRE, BUY_LAND) else "WHEAT"
    action = Action(action_type, target)

    with pytest.raises(ValueError):
        operator.compose(farmer=action)
    with pytest.raises(ValueError):
        operator.compose(hands=[action])


def test_farm_work_cannot_be_sent_to_market(operator):
    with pytest.raises(ValueError):
        operator.compose(market=[Action(PLANT, "WHEAT")])


@pytest.mark.parametrize("action_type", [PLANT, BUY_SEED, BUY_ANIMAL, BUY_PRODUCT, SELL])
def test_targeted_action_requires_target(operator, action_type):
    with pytest.raises(ValueError):
        operator.execute(Decision(Turn.from_action(Action(action_type, None))))


@pytest.mark.parametrize("quantity", [0, -1, 1.5, "2", True])
def test_market_order_rejects_invalid_quantity(operator, quantity):
    with pytest.raises(ValueError):
        operator.to_market_order(Action(SELL, "WHEAT", quantity))


@pytest.mark.parametrize("action_type", [HIRE, BUY_LAND])
def test_atomic_market_action_rejects_target(operator, action_type):
    with pytest.raises(ValueError):
        operator.to_market_order(Action(action_type, "WHEAT"))


@pytest.mark.parametrize("action_type", [HIRE, BUY_LAND])
def test_atomic_market_action_rejects_multiple_units(operator, action_type):
    with pytest.raises(ValueError):
        operator.to_market_order(Action(action_type, None, 2))


def test_plant_rejects_multiple_units(operator):
    with pytest.raises(ValueError):
        operator.to_unit_op(Action(PLANT, "WHEAT", 2))
