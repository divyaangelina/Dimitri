"""Unit tests for the Planner's state evaluator."""

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
from dimitri.planner.action import BUY_PRODUCT, SELL, Action
from dimitri.planner.evaluation import Evaluation
from dimitri.planner.evaluator import Evaluator
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
            prices={"WHEAT": 25, "EGG": 40, "TOMATO": 30} if prices is None else prices,
            inventory={"WHEAT": 10000, "EGG": 9000},
        ),
        town=Town(unlocked_shops=()),
        raw_observation={"day": 3, "hour": 7},
    )


def _evaluate(game_state) -> Evaluation:
    return Evaluator().evaluate(game_state)


def test_cash_is_player_money():
    assert _evaluate(_make_game_state(money=1234)).cash == 1234


def test_inventory_value_is_quantity_times_price():
    assert _evaluate(_make_game_state()).inventory_value == 2 * 25 + 1 * 40


def test_seed_cost_is_quantity_times_seed_price():
    # Fixed seed prices (WHEAT 10, TOMATO 50), not market sale prices.
    assert _evaluate(_make_game_state()).seed_cost == 3 * 10 + 1 * 50


def test_final_objective_value_is_cash():
    evaluation = _evaluate(_make_game_state(money=1000))

    assert evaluation.final_objective_value == 1000
    assert evaluation.final_objective_value == evaluation.cash


def test_inventory_value_is_excluded_from_final_objective_value():
    evaluation = _evaluate(_make_game_state(money=1000))

    assert evaluation.inventory_value == 2 * 25 + 1 * 40
    assert evaluation.final_objective_value == 1000
    assert (
        evaluation.final_objective_value
        != evaluation.cash + evaluation.inventory_value
    )


def test_evaluation_has_no_total_liquid_value():
    assert "total_liquid_value" not in {
        f.name for f in dataclasses.fields(Evaluation)
    }


def test_unknown_inventory_items_contribute_nothing():
    evaluation = _evaluate(_make_game_state(shed={"WHEAT": 2, "MYSTERY": 5}))

    assert evaluation.inventory_value == 2 * 25


def test_unknown_seed_types_contribute_nothing():
    evaluation = _evaluate(_make_game_state(seeds={"WHEAT": 3, "MYSTERY": 4}))

    assert evaluation.seed_cost == 3 * 10


def test_empty_holdings_evaluate_to_zero():
    evaluation = _evaluate(_make_game_state(money=50, shed={}, seeds={}))

    assert evaluation == Evaluation(
        cash=50, inventory_value=0, seed_cost=0, final_objective_value=50
    )


def test_evaluation_is_immutable():
    evaluation = _evaluate(_make_game_state())

    with pytest.raises(dataclasses.FrozenInstanceError):
        evaluation.cash = 0


def test_evaluate_does_not_mutate_game_state():
    game_state = _make_game_state()
    before = copy.deepcopy(game_state)

    _evaluate(game_state)

    assert game_state == before


def test_identical_states_produce_identical_evaluations():
    assert _evaluate(_make_game_state()) == _evaluate(_make_game_state())


def test_cash_change_changes_cash_and_objective_only():
    low = _evaluate(_make_game_state(money=100))
    high = _evaluate(_make_game_state(money=300))

    assert high.cash - low.cash == 200
    assert high.final_objective_value - low.final_objective_value == 200
    assert high.inventory_value == low.inventory_value
    assert high.seed_cost == low.seed_cost


def test_inventory_change_changes_inventory_value_but_not_objective():
    low = _evaluate(_make_game_state(shed={"WHEAT": 1}))
    high = _evaluate(_make_game_state(shed={"WHEAT": 5}))

    assert high.inventory_value - low.inventory_value == 4 * 25
    assert high.final_objective_value == low.final_objective_value
    assert high.cash == low.cash
    assert high.seed_cost == low.seed_cost


def test_seed_change_changes_seed_cost_but_not_objective():
    low = _evaluate(_make_game_state(seeds={"TOMATO": 1}))
    high = _evaluate(_make_game_state(seeds={"TOMATO": 4}))

    assert high.seed_cost - low.seed_cost == 3 * 50
    assert high.final_objective_value == low.final_objective_value
    assert high.inventory_value == low.inventory_value
    assert high.cash == low.cash


def test_buy_and_sell_at_same_price_evaluate_differently():
    game_state = _make_game_state(money=1000, shed={"WHEAT": 2})
    simulator = Simulator()

    bought = _evaluate(simulator.simulate(game_state, Action(BUY_PRODUCT, "WHEAT")))
    sold = _evaluate(simulator.simulate(game_state, Action(SELL, "WHEAT")))

    # Environment quotes at inventory 10000: buying costs 26, selling pays 25.
    assert bought.final_objective_value == 1000 - 26
    assert sold.final_objective_value == 1000 + 25
    assert sold.final_objective_value > bought.final_objective_value
