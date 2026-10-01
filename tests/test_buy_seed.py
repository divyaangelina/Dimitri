"""Tests for BUY_SEED: seed prices, simulation, generation, and the pipeline.

Seed rules come from the installed Kaggriculture environment:

- ``CROPS[crop]["seed"]`` is the fixed price of one seed;
- ``_commit_unit`` fills BUY_SEED one seed at a time while money lasts,
  adding each seed to ``private["seeds"]`` and touching nothing else;
- ``_process_market`` drops orders beyond ``maxMarketOrdersPerTurn``.

The real-environment tests play actual steps and compare the results.
"""

import copy
import json
from pathlib import Path

import pytest

from dimitri.executive.decision import Decision
from dimitri.executive.executive import Executive
from dimitri.observer.parser import parse
from dimitri.pipeline import Pipeline
from dimitri.planner.action import BUY_SEED, Action
from dimitri.planner.evaluator import Evaluator
from dimitri.planner.generator import CandidateGenerator
from dimitri.planner.planner import Planner
from dimitri.planner.simulator import Simulator
from dimitri.planner.turn import Turn
from dimitri.utils.constants import CROPS, MARKET_PARAMS, MAX_MARKET_ORDERS_PER_TURN
from dimitri.utils.valuation import seed_cost

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"

SEED_PRICES = {"WHEAT": 10, "CARROT": 20, "TOMATO": 50, "STRAWBERRY": 100, "MELON": 80}

PLANT_DICT = {
    "kind": "PLANT",
    "crop": "WHEAT",
    "planted_day": 0,
    "watered_today": False,
    "consecutive_unwatered": 1,
    "yield_units": 1,
    "max_lifespan_step": 120,
    "fertilized_until_day": -1,
}


def _state(*, money=3000, seeds=None, shed=None, carried=None, hands=((6, 6),)):
    """A parsed GameState from the sample observation, with some of everything."""
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)
    farm = observation["farms"][observation["player"]]
    farm["money"] = money
    farm["farmer"] = [2, 3]
    farm["hands"] = [list(h) for h in hands]
    farm["tiles"][1][1] = dict(PLANT_DICT)
    private = observation["private"]
    private["seeds"].update(seeds or {})
    private["shed"] = {"EGG": 2, "WHEAT": 1} if shed is None else shed
    inventories = [{"MILK": 1}] + [{} for _ in hands] if carried is None else carried
    private["inventories"] = inventories
    return parse(observation)


def _buy(state, crop, quantity=1):
    return Simulator().simulate(state, Action(BUY_SEED, crop, quantity))


# --- seed prices ---------------------------------------------------------


def test_every_crop_has_the_environment_seed_price():
    assert {crop: rules.seed_price for crop, rules in CROPS.items()} == SEED_PRICES


def test_seed_prices_match_installed_environment():
    env = pytest.importorskip("kaggle_environments.envs.kaggriculture.kaggriculture")

    assert {crop: data["seed"] for crop, data in env.CROPS.items()} == SEED_PRICES


def test_seed_prices_are_not_market_sale_prices():
    # A crop's seed price and its product's base sale price are different facts.
    for crop, price in SEED_PRICES.items():
        assert MARKET_PARAMS[crop].base != price


def test_seed_cost_uses_seed_prices_not_market_prices():
    state = _state(seeds={"WHEAT": 3, "MELON": 1})

    assert seed_cost(state.player.seeds) == 3 * 10 + 1 * 80
    assert Evaluator().evaluate(state).seed_cost == 3 * 10 + 1 * 80


# --- simulation ----------------------------------------------------------


@pytest.mark.parametrize(("crop", "price"), sorted(SEED_PRICES.items()))
def test_buying_one_seed_costs_its_seed_price(crop, price):
    state = _state(money=500)

    result = _buy(state, crop)

    assert result.player.money == 500 - price
    assert result.player.seeds[crop] == state.player.seeds[crop] + 1


def test_buying_seeds_adds_to_existing_seeds():
    result = _buy(_state(seeds={"TOMATO": 2}), "TOMATO", 3)

    assert result.player.seeds["TOMATO"] == 5


def test_buying_seeds_changes_only_money_and_seeds():
    state = _state(money=500)

    result = _buy(state, "CARROT", 2)

    assert result.market == state.market
    assert result.player.inventory == state.player.inventory
    assert result.player.unit_inventories == state.player.unit_inventories
    assert result.player.farm == state.player.farm
    assert result.player.farm.farmer == [2, 3]
    assert result.player.farm.hands == [[6, 6]]
    assert result.opponent == state.opponent
    assert result.town == state.town
    assert {c: n for c, n in result.player.seeds.items() if c != "CARROT"} == {
        c: n for c, n in state.player.seeds.items() if c != "CARROT"
    }


def test_multi_unit_purchase_charges_every_seed():
    result = _buy(_state(money=1000), "MELON", 4)

    assert result.player.money == 1000 - 4 * 80
    assert result.player.seeds["MELON"] == 4


def test_unaffordable_purchase_fills_partially():
    result = _buy(_state(money=45), "CARROT", 5)

    assert result.player.seeds["CARROT"] == 2
    assert result.player.money == 5


def test_purchase_that_fills_no_seed_is_rejected():
    with pytest.raises(ValueError, match="Cannot afford"):
        _buy(_state(money=99), "STRAWBERRY")


def test_seed_purchase_ignores_full_shed():
    state = _state(money=100, shed={"WHEAT": 100})

    result = _buy(state, "WHEAT", 2)

    assert result.player.seeds["WHEAT"] == 2
    assert result.player.inventory == state.player.inventory


@pytest.mark.parametrize("crop", ["EGG", "FERTILIZER", "GOOSE", "wheat", "", None])
def test_invalid_seed_type_is_rejected(crop):
    with pytest.raises(ValueError, match="cannot be bought"):
        _buy(_state(), crop)


@pytest.mark.parametrize("quantity", [0, -1, 1.5, True, "2"])
def test_invalid_quantity_is_rejected(quantity):
    with pytest.raises(ValueError, match="positive integer"):
        _buy(_state(), "WHEAT", quantity)


def test_buy_seed_does_not_mutate_original():
    state = _state()
    before = copy.deepcopy(state)

    _buy(state, "TOMATO", 2)

    assert state == before


def test_buy_seed_is_rejected_for_a_unit():
    with pytest.raises(ValueError, match="cannot be performed by a unit"):
        Simulator().simulate_turn(_state(), Turn(farmer=Action(BUY_SEED, "WHEAT")))


def test_seed_orders_in_one_turn_share_the_same_money():
    state = _state(money=100)
    turn = Turn(market=(Action(BUY_SEED, "MELON"), Action(BUY_SEED, "WHEAT", 5)))

    result = Simulator().simulate_turn(state, turn)

    # MELON leaves 20, which buys only 2 of the 5 WHEAT seeds.
    assert result.player.money == 0
    assert (result.player.seeds["MELON"], result.player.seeds["WHEAT"]) == (1, 2)


def test_market_order_limit_is_respected():
    orders = (Action(BUY_SEED, "WHEAT"),) * MAX_MARKET_ORDERS_PER_TURN

    result = Simulator().simulate_turn(_state(money=1000), Turn(market=orders))
    assert result.player.seeds["WHEAT"] == MAX_MARKET_ORDERS_PER_TURN

    with pytest.raises(ValueError, match="At most"):
        Simulator().simulate_turn(
            _state(money=1000), Turn(market=(*orders, Action(BUY_SEED, "WHEAT")))
        )


# --- generation ----------------------------------------------------------


def _seed_actions(state):
    return [a for a in CandidateGenerator().generate(state) if a.action_type == BUY_SEED]


def test_every_affordable_seed_is_generated_once_in_crops_order():
    assert _seed_actions(_state(money=1000)) == [
        Action(BUY_SEED, crop, 1) for crop in CROPS
    ]


def test_only_affordable_seeds_are_generated():
    assert _seed_actions(_state(money=50)) == [
        Action(BUY_SEED, "WHEAT", 1),
        Action(BUY_SEED, "CARROT", 1),
        Action(BUY_SEED, "TOMATO", 1),
    ]


def test_no_seed_is_generated_when_none_is_affordable():
    assert _seed_actions(_state(money=9)) == []


def test_generated_seed_purchases_can_all_be_simulated():
    state = _state(money=80)

    for action in _seed_actions(state):
        result = Simulator().simulate(state, action)
        assert result.player.money == 80 - CROPS[action.target].seed_price


def test_generation_does_not_depend_on_market_prices():
    # Seed choice is not a crop-profitability judgement: prices do not matter.
    state = _state(money=1000)
    repriced = copy.deepcopy(state)
    object.__setattr__(repriced.market, "prices", {crop: 1 for crop in CROPS})

    assert _seed_actions(repriced) == _seed_actions(state)


# --- evaluation and selection -------------------------------------------


def test_buying_seeds_reduces_immediate_cash():
    state = _state(money=500)

    evaluation = Evaluator().evaluate(_buy(state, "TOMATO"))

    assert evaluation.final_objective_value == 500 - 50
    assert evaluation.seed_cost == Evaluator().evaluate(state).seed_cost + 50


def test_idle_is_preferred_to_a_seed_purchase_under_cash_objective():
    state = _state(money=500, shed={}, carried=[{}, {}])
    result = Planner().plan(state)
    seed_candidates = [
        c for c in result.candidates
        if any(a.action_type == BUY_SEED for a in c.turn.market)
    ]

    assert seed_candidates
    assert all(c.evaluation.final_objective_value < 500 for c in seed_candidates)
    assert Executive().decide(result).turn.actions() == ()


# --- the pipeline --------------------------------------------------------


class _PickSeedPurchase(Executive):
    """Commits to the first BUY_SEED candidate, to exercise the plumbing."""

    def decide(self, planning_result):
        for candidate in planning_result.candidates:
            if any(a.action_type == BUY_SEED for a in candidate.turn.market):
                return Decision(turn=candidate.turn)
        raise AssertionError("no BUY_SEED candidate")


def test_buy_seed_decision_reaches_the_operator():
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)

    api_action = Pipeline(executive=_PickSeedPurchase()).run(observation)

    assert api_action == {
        "farmer": ["PASS"],
        "hands": [],
        "market": [["BUY_SEED", "WHEAT", 1]],
    }


# --- the real environment ------------------------------------------------


def _play(market_orders, *, starting_money=3000):
    """Play two steps; on step 1 send ``market_orders``. Return observations 1 and 2."""
    kaggle_environments = pytest.importorskip("kaggle_environments")
    received = {}

    def agent(obs):
        received[obs["step"]] = copy.deepcopy(dict(obs))
        orders = market_orders if obs["step"] == 1 else []
        return {"farmer": ["PASS"], "hands": [], "market": orders}

    env = kaggle_environments.make(
        "kaggriculture",
        configuration={"episodeSteps": 4, "startingMoney": starting_money, "seed": 7},
        debug=True,
    )
    env.run([agent, "pass"])
    return parse(received[1]), parse(received[2])


@pytest.mark.parametrize(
    ("starting_money", "orders"),
    [
        (3000, [["BUY_SEED", "WHEAT", 1]]),
        (3000, [["BUY_SEED", "MELON", 3], ["BUY_SEED", "TOMATO", 2]]),
        (3000, [["BUY_SEED", crop, 1] for crop in SEED_PRICES]),
        # Partial fill: 45 buys only 2 of 5 CARROT seeds.
        (45, [["BUY_SEED", "CARROT", 5]]),
        # The second order is cut short by the money the first one spent.
        (100, [["BUY_SEED", "MELON", 1], ["BUY_SEED", "WHEAT", 5]]),
    ],
)
def test_buy_seed_matches_real_environment(starting_money, orders):
    before, after = _play(orders, starting_money=starting_money)
    turn = Turn(market=tuple(Action(*order) for order in orders))

    predicted = Simulator().simulate_turn(before, turn)

    assert predicted.player == after.player
    assert predicted.player.money == after.player.money
    assert predicted.player.seeds == after.player.seeds


def test_real_environment_buy_seed_leaves_market_untouched():
    # Same seed, with and without a seed purchase: the market evolves identically.
    _, bought = _play([["BUY_SEED", "STRAWBERRY", 5]])
    _, idle = _play([])

    assert bought.market == idle.market
    assert bought.player.seeds["STRAWBERRY"] == 5
    assert idle.player.money - bought.player.money == 5 * 100


def test_environment_ignores_a_seed_order_the_simulator_rejects():
    before, after = _play([["BUY_SEED", "STRAWBERRY", 1]], starting_money=99)

    assert after.player == before.player
    with pytest.raises(ValueError, match="Cannot afford"):
        Simulator().simulate_turn(
            before, Turn(market=(Action(BUY_SEED, "STRAWBERRY"),))
        )
