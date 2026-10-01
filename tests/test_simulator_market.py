"""Tests for the Simulator's BUY_PRODUCT and SELL behavior.

Market rules come from the installed Kaggriculture environment
(``_process_market``, ``_commit_unit``, ``market_price``): orders fill
one unit at a time, each unit priced from the market inventory at that
moment. Only WHEAT and FERTILIZER can be bought, and only market
products can be sold. Purchases stop when money runs short or the shed
is full, and sales stop when the shed runs out. The last tests play
real environment steps and compare the results with the Simulator's.
"""

import copy
import json
from pathlib import Path

import pytest

from dimitri.observer.parser import parse
from dimitri.planner.action import BUY_PRODUCT, SELL, Action
from dimitri.planner.rules import buy_quote, market_price, sell_quote
from dimitri.planner.simulator import Simulator
from dimitri.planner.turn import Turn
from dimitri.utils.constants import (
    BUYABLE_PRODUCTS,
    MARKET_PARAMS,
    MAX_MARKET_ORDERS_PER_TURN,
    PRODUCTS,
    SHED_CAPACITY,
)

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"


def _state(*, money=3000, shed=None, market_inventory=None):
    """A parsed GameState from the sample observation with overrides."""
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)
    observation["farms"][0]["money"] = money
    observation["private"]["shed"].update(shed or {})
    market = observation["market"]
    market["inventory"].update(market_inventory or {})
    for item, inventory in market["inventory"].items():
        market["prices"][item] = market_price(item, inventory)
    return parse(observation)


def _simulate(state, action_type, target, quantity=1):
    return Simulator().simulate(state, Action(action_type, target, quantity))


# --- price function -----------------------------------------------------


def test_price_function_matches_environment():
    env = pytest.importorskip("kaggle_environments.envs.kaggriculture.kaggriculture")
    inventories = [0, 1, 500, 9_000, 9_999, 10_000, 10_001, 11_000, 50_000, 10**6]

    for item in env.PRODUCTS:
        for inventory in inventories:
            assert market_price(item, inventory) == env.market_price(item, inventory)


def test_market_constants_match_environment():
    env = pytest.importorskip("kaggle_environments.envs.kaggriculture.kaggriculture")

    assert PRODUCTS == tuple(env.PRODUCTS)
    for item, curve in MARKET_PARAMS.items():
        assert vars(curve) == env.MARKET_PARAMS[item]


def test_buy_quote_is_price_at_post_buy_inventory():
    assert buy_quote("WHEAT", 10_000) == market_price("WHEAT", 9_999) == 26
    assert sell_quote("WHEAT", 10_000) == market_price("WHEAT", 10_000) == 25


# --- BUY_PRODUCT --------------------------------------------------------


@pytest.mark.parametrize("item", sorted(BUYABLE_PRODUCTS))
def test_buy_product_moves_one_unit_from_market_to_shed(item):
    state = _state()
    price = buy_quote(item, state.market.inventory[item])

    result = _simulate(state, BUY_PRODUCT, item)

    assert result.player.money == state.player.money - price
    assert result.player.inventory.items[item] == state.player.inventory.items[item] + 1
    assert result.market.inventory[item] == state.market.inventory[item] - 1
    assert result.market.prices[item] == market_price(item, result.market.inventory[item])


@pytest.mark.parametrize("item", ["EGG", "CARROT", "MILK", "GOOSE", "COW", "TRUFFLE"])
def test_buy_product_rejects_items_the_environment_does_not_sell(item):
    with pytest.raises(ValueError, match="cannot be bought"):
        _simulate(_state(), BUY_PRODUCT, item)


def test_multi_unit_buy_is_priced_one_unit_at_a_time():
    state = _state()
    quotes = [buy_quote("WHEAT", 10_000 - n) for n in range(10)]
    assert len(set(quotes)) > 1  # the price rises as the order fills

    result = _simulate(state, BUY_PRODUCT, "WHEAT", 10)

    assert result.player.money == 3000 - sum(quotes)
    assert sum(quotes) != 10 * state.market.prices["WHEAT"]
    assert result.market.inventory["WHEAT"] == 9_990
    assert result.player.inventory.items["WHEAT"] == 10


def test_buy_stops_when_money_runs_out():
    result = _simulate(_state(money=60), BUY_PRODUCT, "WHEAT", 5)

    assert result.player.inventory.items["WHEAT"] == 2
    assert result.player.money == 60 - 26 - 26


def test_buy_that_cannot_afford_one_unit_raises():
    with pytest.raises(ValueError, match="Cannot afford"):
        _simulate(_state(money=25), BUY_PRODUCT, "WHEAT")


def test_buy_stops_at_shed_capacity():
    # Animals count toward the shed's capacity; seeds do not.
    state = _state(money=100_000, shed={"EGG": 90, "GOOSE": 5})

    result = _simulate(state, BUY_PRODUCT, "FERTILIZER", 50)

    assert result.player.inventory.items["FERTILIZER"] == 5
    assert sum(result.player.inventory.items.values()) == SHED_CAPACITY
    assert result.market.inventory["FERTILIZER"] == state.market.inventory["FERTILIZER"] - 5


def test_buy_with_full_shed_raises():
    with pytest.raises(ValueError, match="Shed is full"):
        _simulate(_state(shed={"WOOL": SHED_CAPACITY}), BUY_PRODUCT, "WHEAT")


def test_buy_does_not_touch_seeds_unit_inventories_or_farm():
    state = _state()

    result = _simulate(state, BUY_PRODUCT, "WHEAT", 3)

    assert result.player.seeds == state.player.seeds
    assert result.player.unit_inventories == state.player.unit_inventories
    assert result.player.farm == state.player.farm
    assert result.opponent == state.opponent


# --- SELL ---------------------------------------------------------------


def test_sell_moves_one_unit_from_shed_to_market():
    state = _state(shed={"MILK": 3})

    result = _simulate(state, SELL, "MILK")

    assert result.player.money == 3000 + sell_quote("MILK", 10_000)
    assert result.player.inventory.items["MILK"] == 2
    assert result.market.inventory["MILK"] == 10_001
    assert result.market.prices["MILK"] == market_price("MILK", 10_001)


def test_multi_unit_sell_is_priced_one_unit_at_a_time():
    state = _state(shed={"MELON": 10})
    expected = sum(sell_quote("MELON", 10_000 + n) for n in range(10))

    result = _simulate(state, SELL, "MELON", 10)

    assert result.player.money == 3000 + expected
    assert expected != 10 * state.market.prices["MELON"]
    assert result.player.inventory.items["MELON"] == 0
    assert result.market.inventory["MELON"] == 10_010


def test_sell_stops_when_shed_runs_out():
    result = _simulate(_state(shed={"EGG": 2}), SELL, "EGG", 5)

    assert result.player.inventory.items["EGG"] == 0
    assert result.player.money == 3000 + sell_quote("EGG", 10_000) + sell_quote("EGG", 10_001)


def test_sale_at_price_floor_does_not_add_to_market_inventory():
    # MELON is floored at $1 once its inventory is far above I0.
    state = _state(shed={"MELON": 2}, market_inventory={"MELON": 20_000})
    assert market_price("MELON", 20_000) == 1

    result = _simulate(state, SELL, "MELON", 2)

    assert result.player.money == 3000 + 2
    assert result.market.inventory["MELON"] == 20_000


@pytest.mark.parametrize("item", ["GOOSE", "COW", "SHEEP", "TRUFFLE"])
def test_sell_rejects_items_that_are_not_market_products(item):
    with pytest.raises(ValueError, match="cannot be sold"):
        _simulate(_state(shed={item: 1}), SELL, item)


def test_sell_with_nothing_in_shed_raises():
    with pytest.raises(ValueError, match="none in the shed"):
        _simulate(_state(), SELL, "WHEAT")


# --- turns, immutability, and determinism ------------------------------


def test_orders_in_a_turn_see_each_others_market_effects():
    state = _state(shed={"WHEAT": 5})
    turn = Turn(market=(Action(SELL, "WHEAT", 5), Action(BUY_PRODUCT, "WHEAT", 1)))

    result = Simulator().simulate_turn(state, turn)

    assert result.market.inventory["WHEAT"] == 10_004
    assert result.player.money == (
        3000
        + sum(sell_quote("WHEAT", 10_000 + n) for n in range(5))
        - buy_quote("WHEAT", 10_005)
    )


def test_turn_with_too_many_market_orders_raises():
    orders = tuple(Action(SELL, "WHEAT") for _ in range(MAX_MARKET_ORDERS_PER_TURN + 1))

    with pytest.raises(ValueError, match="market orders"):
        Simulator().simulate_turn(_state(shed={"WHEAT": 20}), Turn(market=orders))


@pytest.mark.parametrize(
    ("action_type", "target", "shed"),
    [(BUY_PRODUCT, "WHEAT", {}), (SELL, "EGG", {"EGG": 4})],
)
def test_market_simulation_does_not_mutate_original(action_type, target, shed):
    state = _state(shed=shed)
    snapshot = copy.deepcopy(state)

    _simulate(state, action_type, target, 3)

    assert state == snapshot


def test_failed_order_does_not_mutate_original():
    state = _state(money=0)
    snapshot = copy.deepcopy(state)

    with pytest.raises(ValueError):
        _simulate(state, BUY_PRODUCT, "WHEAT")

    assert state == snapshot


def test_market_simulation_is_deterministic():
    state = _state(shed={"TOMATO": 7})
    action = Action(SELL, "TOMATO", 7)

    assert Simulator().simulate(state, action) == Simulator().simulate(state, action)


# --- parity with the real environment ----------------------------------

# Market orders submitted at each step. Steps are chosen so that no town
# consumption happens in the same step (none at step % 12 == 0 here, and
# no shops unlock before day 3), and the opponent passes.
_ENV_ORDERS = {
    1: [["BUY_PRODUCT", "WHEAT", 120]],  # stops when money runs out
    2: [["SELL", "WHEAT", 30]],
    3: [["BUY_PRODUCT", "FERTILIZER", 5], ["SELL", "WHEAT", 2]],
    4: [["SELL", "WHEAT", 500]],  # stops when the shed runs out
    5: [["BUY_PRODUCT", "FERTILIZER", 1000]],  # stops when money runs out
}


def _play(orders, configuration=None):
    """Play a short real game and return the observations Dimitri received."""
    kaggle_environments = pytest.importorskip("kaggle_environments")
    received = {}

    def agent(obs):
        received[obs["step"]] = copy.deepcopy(dict(obs))
        return {"farmer": ["PASS"], "hands": [], "market": orders.get(obs["step"], [])}

    env = kaggle_environments.make(
        "kaggriculture",
        configuration={"episodeSteps": max(orders) + 3, **(configuration or {})},
        debug=True,
    )
    env.run([agent, "pass"])
    return received


def _assert_matches_environment(received, step, orders):
    before, after = parse(received[step]), parse(received[step + 1])
    turn = Turn(market=tuple(Action(op, item, n) for op, item, n in orders))

    predicted = Simulator().simulate_turn(before, turn)

    assert predicted.player.money == after.player.money
    assert predicted.player.inventory == after.player.inventory
    assert dict(predicted.market.inventory) == dict(after.market.inventory)
    assert dict(predicted.market.prices) == dict(after.market.prices)


def test_market_orders_match_real_environment_steps():
    received = _play(_ENV_ORDERS)

    for step, orders in _ENV_ORDERS.items():
        _assert_matches_environment(received, step, orders)


def test_shed_capacity_matches_real_environment():
    orders = {1: [["BUY_PRODUCT", "WHEAT", 150]]}
    received = _play(orders, configuration={"startingMoney": 10_000})

    _assert_matches_environment(received, 1, orders[1])
    assert parse(received[2]).player.inventory.items["WHEAT"] == SHED_CAPACITY
