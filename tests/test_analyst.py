"""Unit tests for the Analyst's deterministic derived facts."""

import copy
from dataclasses import FrozenInstanceError

import pytest

from dimitri.analyst.analysis import Analysis
from dimitri.analyst.analyst import Analyst
from dimitri.analyst.opportunity import EconomicOpportunity
from dimitri.models.farm import Farm
from dimitri.models.game_state import GameState
from dimitri.models.inventory import Inventory
from dimitri.models.market import Market
from dimitri.models.opponent import Opponent
from dimitri.models.player import Player
from dimitri.utils.constants import SEASON_LENGTH_DAYS

WHEAT_TILE = {"type": "WHEAT", "planted_day": 0}
COW_TILE = {"type": "COW", "placed_day": 1}

# 3x4 board: 5 empty, 4 locked, 3 occupied.
MIXED_TILES = [
    [None, None, "LOCKED", "LOCKED"],
    [WHEAT_TILE, None, "LOCKED", "LOCKED"],
    [None, COW_TILE, None, WHEAT_TILE],
]


def _make_farm(tiles) -> Farm:
    return Farm(
        tiles=tiles,
        farmer=[0, 0],
        hands=[],
        unlocked_quadrants=["NW"],
        hires_today=0,
    )


def _make_game_state(
    day=0,
    hour=0,
    money=3000,
    tiles=MIXED_TILES,
    shed=None,
    seeds=None,
    prices=None,
    market_inventory=None,
) -> GameState:
    return GameState(
        day=day,
        hour=hour,
        player=Player(
            player_id=0,
            money=money,
            inventory=Inventory(items={"WHEAT": 2} if shed is None else shed),
            seeds={"WHEAT": 5} if seeds is None else seeds,
            farm=_make_farm(tiles),
        ),
        opponent=Opponent(
            player_id=1,
            money=3000,
            farm=_make_farm([["LOCKED", None]]),
        ),
        market=Market(
            prices={"WHEAT": 25} if prices is None else prices,
            inventory={"WHEAT": 10} if market_inventory is None else market_inventory,
        ),
        raw_observation={"day": day, "hour": hour},
    )


def test_analyze_returns_analysis():
    assert isinstance(Analyst().analyze(_make_game_state()), Analysis)


def test_current_day_and_hour():
    analysis = Analyst().analyze(_make_game_state(day=7, hour=13))

    assert analysis.current_day == 7
    assert analysis.current_hour == 13


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (0, SEASON_LENGTH_DAYS),
        (12, SEASON_LENGTH_DAYS - 12),
        (SEASON_LENGTH_DAYS - 1, 1),
    ],
)
def test_days_remaining(day, expected):
    assert Analyst().analyze(_make_game_state(day=day)).days_remaining == expected


def test_current_money():
    assert Analyst().analyze(_make_game_state(money=1234)).current_money == 1234


def test_tile_counts_for_mixed_farm():
    analysis = Analyst().analyze(_make_game_state(tiles=MIXED_TILES))

    assert analysis.unlocked_tiles == 8
    assert analysis.locked_tiles == 4
    assert analysis.occupied_tiles == 3
    assert analysis.empty_tiles == 5


def test_tile_counts_all_locked():
    tiles = [["LOCKED"] * 3 for _ in range(2)]
    analysis = Analyst().analyze(_make_game_state(tiles=tiles))

    assert analysis.unlocked_tiles == 0
    assert analysis.locked_tiles == 6
    assert analysis.occupied_tiles == 0
    assert analysis.empty_tiles == 0


def test_tile_counts_all_empty():
    tiles = [[None] * 5 for _ in range(5)]
    analysis = Analyst().analyze(_make_game_state(tiles=tiles))

    assert analysis.unlocked_tiles == 25
    assert analysis.locked_tiles == 0
    assert analysis.occupied_tiles == 0
    assert analysis.empty_tiles == 25


def test_tile_counts_ignore_opponent_farm():
    """Only Dimitri's own farm is counted, not the opponent's."""
    analysis = Analyst().analyze(_make_game_state(tiles=[[None]]))

    assert analysis.locked_tiles == 0
    assert analysis.empty_tiles == 1


def test_game_state_unchanged_after_analysis():
    game_state = _make_game_state()
    before = copy.deepcopy(game_state)

    Analyst().analyze(game_state)

    assert game_state == before
    assert game_state.raw_observation == before.raw_observation


def test_analysis_is_immutable():
    analysis = Analyst().analyze(_make_game_state())

    with pytest.raises(FrozenInstanceError):
        analysis.current_money = 0


PRICES = {"WHEAT": 25, "CARROT": 35, "EGG": 50, "MILK": 160}


def test_market_prices_copied():
    analysis = Analyst().analyze(_make_game_state(prices=PRICES))

    assert analysis.market_prices == PRICES


def test_market_inventory_copied():
    supply = {"WHEAT": 10000, "EGG": 9000}
    analysis = Analyst().analyze(_make_game_state(market_inventory=supply))

    assert analysis.market_inventory == supply


def test_inventory_total_value():
    shed = {"WHEAT": 4, "EGG": 3, "MILK": 0}
    analysis = Analyst().analyze(_make_game_state(shed=shed, prices=PRICES))

    assert analysis.inventory_total_value == 4 * 25 + 3 * 50


def test_seed_total_cost():
    seeds = {"WHEAT": 5, "CARROT": 2}
    analysis = Analyst().analyze(_make_game_state(seeds=seeds, prices=PRICES))

    assert analysis.seed_total_cost == 5 * 25 + 2 * 35


def test_unpriced_inventory_items_are_skipped():
    shed = {"WHEAT": 2, "GOOSE": 7, "MYSTERY": 3}
    analysis = Analyst().analyze(_make_game_state(shed=shed, prices=PRICES))

    assert analysis.inventory_total_value == 2 * 25


def test_unpriced_seed_types_are_skipped():
    seeds = {"CARROT": 1, "PUMPKIN": 9}
    analysis = Analyst().analyze(_make_game_state(seeds=seeds, prices=PRICES))

    assert analysis.seed_total_cost == 35


def test_empty_holdings_value_to_zero():
    analysis = Analyst().analyze(_make_game_state(shed={}, seeds={}, prices=PRICES))

    assert analysis.inventory_total_value == 0
    assert analysis.seed_total_cost == 0


def test_analysis_economic_fields_are_immutable():
    analysis = Analyst().analyze(_make_game_state(prices=PRICES))

    with pytest.raises(FrozenInstanceError):
        analysis.inventory_total_value = 0
    with pytest.raises(FrozenInstanceError):
        analysis.market_prices = {}
    with pytest.raises(TypeError):
        analysis.market_prices["WHEAT"] = 1
    with pytest.raises(TypeError):
        analysis.market_inventory["WHEAT"] = 1


def test_mutating_source_mappings_does_not_change_analysis():
    prices = dict(PRICES)
    supply = {"WHEAT": 10}
    game_state = _make_game_state(prices=prices, market_inventory=supply)
    analysis = Analyst().analyze(game_state)

    prices["WHEAT"] = 999
    prices["NEW"] = 1
    supply["WHEAT"] = 0

    assert analysis.market_prices == PRICES
    assert analysis.market_inventory == {"WHEAT": 10}


def test_economic_facts_leave_game_state_unchanged():
    game_state = _make_game_state(
        shed={"WHEAT": 2, "GOOSE": 1},
        seeds={"CARROT": 3, "PUMPKIN": 1},
        prices=dict(PRICES),
    )
    before = copy.deepcopy(game_state)

    Analyst().analyze(game_state)

    assert game_state == before


def test_one_opportunity_per_market_item():
    analysis = Analyst().analyze(_make_game_state(prices=PRICES))

    assert len(analysis.economic_opportunities) == len(PRICES)
    assert all(
        isinstance(opportunity, EconomicOpportunity)
        for opportunity in analysis.economic_opportunities
    )
    assert {o.item for o in analysis.economic_opportunities} == set(PRICES)


def test_opportunity_fields_match_market_price():
    analysis = Analyst().analyze(_make_game_state(prices=PRICES))

    for opportunity in analysis.economic_opportunities:
        price = PRICES[opportunity.item]
        assert opportunity.buy_cost == price
        assert opportunity.sell_price == price
        assert opportunity.gross_margin == (
            opportunity.sell_price - opportunity.buy_cost
        )
        assert opportunity.gross_margin == 0


def test_opportunity_ordering_follows_price_mapping():
    prices = {"MILK": 160, "WHEAT": 25, "EGG": 50, "CARROT": 35}
    analysis = Analyst().analyze(_make_game_state(prices=prices))

    assert [o.item for o in analysis.economic_opportunities] == list(prices)


def test_no_opportunities_for_empty_market():
    analysis = Analyst().analyze(_make_game_state(prices={}))

    assert analysis.economic_opportunities == ()


def test_economic_opportunities_are_immutable():
    analysis = Analyst().analyze(_make_game_state(prices=PRICES))

    assert isinstance(analysis.economic_opportunities, tuple)
    with pytest.raises(FrozenInstanceError):
        analysis.economic_opportunities = ()
    with pytest.raises(FrozenInstanceError):
        analysis.economic_opportunities[0].buy_cost = 0


def test_mutating_source_prices_does_not_change_opportunities():
    prices = dict(PRICES)
    analysis = Analyst().analyze(_make_game_state(prices=prices))
    before = analysis.economic_opportunities

    prices["WHEAT"] = 999
    prices["NEW"] = 1
    del prices["EGG"]

    assert analysis.economic_opportunities == before
    assert [o.item for o in analysis.economic_opportunities] == list(PRICES)
    assert analysis.economic_opportunities[0].buy_cost == PRICES["WHEAT"]


def test_opportunities_leave_game_state_unchanged():
    game_state = _make_game_state(prices=dict(PRICES))
    before = copy.deepcopy(game_state)

    Analyst().analyze(game_state)

    assert game_state == before
