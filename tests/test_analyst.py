"""Unit tests for the Analyst's deterministic derived facts."""

import copy
from dataclasses import FrozenInstanceError

import pytest

from dimitri.analyst.analysis import Analysis
from dimitri.analyst.analyst import Analyst
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


def _make_game_state(day=0, hour=0, money=3000, tiles=MIXED_TILES) -> GameState:
    return GameState(
        day=day,
        hour=hour,
        player=Player(
            player_id=0,
            money=money,
            inventory=Inventory(items={"WHEAT": 2}),
            seeds={"WHEAT": 5},
            farm=_make_farm(tiles),
        ),
        opponent=Opponent(
            player_id=1,
            money=3000,
            farm=_make_farm([["LOCKED", None]]),
        ),
        market=Market(prices={"WHEAT": 25}, inventory={"WHEAT": 10}),
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
