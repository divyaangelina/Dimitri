"""Tests for movement actions: representation, Operator output, and simulation.

Movement rules come from the installed Kaggriculture environment
(``FARMER_MOVES`` and ``_apply_unit_action``):

- positions are ``[x, y]`` and ``y`` grows downward, so NORTH is ``y - 1``;
- a move that would leave the board is a no-op in the environment;
- LOCKED tiles, occupied tiles, and tiles holding another unit can all
  be entered;
- the farmer and hands move by exactly the same rule.

The last test plays real environment steps and compares the results.
"""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from dimitri.executive.decision import Decision
from dimitri.models.tile import PlantTile
from dimitri.observer.parser import parse
from dimitri.operator.operator import Operator
from dimitri.planner.action import (
    EAST,
    MARKET_ACTION_TYPES,
    MOVEMENT_ACTION_TYPES,
    NORTH,
    PLANT,
    SOUTH,
    WEST,
    Action,
)
from dimitri.planner.generator import CandidateGenerator
from dimitri.planner.rules import MOVES
from dimitri.planner.simulator import Simulator
from dimitri.planner.turn import Turn

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"

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


def _state(*, farmer=(4, 4), hands=(), tiles=None, seeds=None):
    """A parsed GameState from the sample observation (10x10 board, NW unlocked)."""
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)
    farm = observation["farms"][0]
    farm["farmer"] = list(farmer)
    farm["hands"] = [list(h) for h in hands]
    for (x, y), tile in (tiles or {}).items():
        farm["tiles"][y][x] = tile
    observation["private"]["seeds"].update(seeds or {})
    observation["private"]["inventories"] = [{} for _ in range(1 + len(hands))]
    return parse(observation)


def _move(state, direction, *, unit=0):
    return Simulator().simulate(state, Action(direction), unit=unit)


# --- representation -----------------------------------------------------


def test_movement_action_types_are_the_four_directions():
    assert MOVEMENT_ACTION_TYPES == {"NORTH", "SOUTH", "EAST", "WEST"}
    assert not MOVEMENT_ACTION_TYPES & MARKET_ACTION_TYPES


def test_movement_action_has_no_target():
    assert Action(NORTH) == Action(action_type="NORTH", target=None, quantity=1)


def test_movement_is_given_to_the_farmer_by_from_action():
    assert Turn.from_action(Action(WEST)) == Turn(farmer=Action(WEST))


def test_move_directions_match_environment():
    env = pytest.importorskip("kaggle_environments.envs.kaggriculture.kaggriculture")

    assert MOVES == env.FARMER_MOVES


# --- all four directions ------------------------------------------------


@pytest.mark.parametrize(
    ("direction", "expected"),
    [(NORTH, [2, 1]), (SOUTH, [2, 3]), (EAST, [3, 2]), (WEST, [1, 2])],
)
def test_farmer_moves_one_tile_in_each_direction(direction, expected):
    result = _move(_state(farmer=(2, 2)), direction)

    assert result.player.farm.farmer == expected


@pytest.mark.parametrize(
    ("direction", "expected"),
    [(NORTH, [2, 1]), (SOUTH, [2, 3]), (EAST, [3, 2]), (WEST, [1, 2])],
)
def test_hand_moves_by_the_same_rule(direction, expected):
    state = _state(farmer=(0, 0), hands=[(7, 7), (2, 2)])

    result = _move(state, direction, unit=2)

    assert result.player.farm.hands == [[7, 7], expected]
    assert result.player.farm.farmer == [0, 0]


def test_farmer_move_leaves_hands_in_place():
    state = _state(hands=[(5, 4)])

    result = _move(state, NORTH)

    assert result.player.farm.farmer == [4, 3]
    assert result.player.farm.hands == [[5, 4]]


# --- boundary, locked, and occupied tiles ------------------------------


@pytest.mark.parametrize(
    ("position", "direction"),
    [((0, 5), WEST), ((9, 5), EAST), ((5, 0), NORTH), ((5, 9), SOUTH), ((0, 0), NORTH)],
)
def test_move_off_the_board_is_rejected(position, direction):
    with pytest.raises(ValueError, match="off the board"):
        _move(_state(farmer=position), direction)


@pytest.mark.parametrize(
    ("position", "direction"),
    [((0, 5), WEST), ((9, 5), EAST), ((5, 0), NORTH), ((5, 9), SOUTH)],
)
def test_hand_move_off_the_board_is_rejected(position, direction):
    with pytest.raises(ValueError, match="off the board"):
        _move(_state(hands=[position]), direction, unit=1)


def test_move_onto_a_locked_tile_is_allowed():
    state = _state(farmer=(4, 4))
    assert state.player.farm.tiles[4][5] == "LOCKED"

    assert _move(state, EAST).player.farm.farmer == [5, 4]


def test_move_across_locked_tiles_is_allowed():
    state = _state(farmer=(7, 7))

    assert _move(state, NORTH).player.farm.farmer == [7, 6]


def test_move_onto_an_occupied_tile_is_allowed():
    state = _state(farmer=(3, 4), tiles={(4, 4): PLANT_DICT})

    result = _move(state, EAST)

    assert result.player.farm.farmer == [4, 4]
    assert isinstance(result.player.farm.tiles[4][4], PlantTile)


def test_units_may_share_a_tile():
    state = _state(farmer=(4, 4), hands=[(5, 4)])

    result = _move(state, WEST, unit=1)

    assert result.player.farm.hands == [[4, 4]]
    assert result.player.farm.farmer == [4, 4]


def test_move_by_missing_hand_is_rejected():
    with pytest.raises(ValueError, match="Unit 1 does not exist"):
        _move(_state(), NORTH, unit=1)


@pytest.mark.parametrize(
    "action", [Action(NORTH, target="WHEAT"), Action(NORTH, quantity=2), Action(NORTH, quantity=0)]
)
def test_malformed_move_is_rejected(action):
    with pytest.raises(ValueError):
        Simulator().simulate(_state(), action)


# --- preservation and immutability -------------------------------------


def test_move_changes_only_the_acting_unit_position():
    state = _state(hands=[(5, 4)])

    result = _move(state, SOUTH, unit=1)

    assert replace(result.player.farm, hands=None) == replace(state.player.farm, hands=None)
    assert replace(result.player, farm=None) == replace(state.player, farm=None)
    assert replace(result, player=None) == replace(state, player=None)


def test_move_does_not_mutate_original():
    state = _state(hands=[(5, 4)])
    snapshot = copy.deepcopy(state)

    _move(state, NORTH)
    _move(state, WEST, unit=1)

    assert state == snapshot


def test_rejected_move_does_not_mutate_original():
    state = _state(farmer=(0, 0))
    snapshot = copy.deepcopy(state)

    with pytest.raises(ValueError):
        _move(state, NORTH)

    assert state == snapshot


def test_moved_positions_do_not_alias_the_original():
    state = _state(hands=[(5, 4)])

    result = _move(state, NORTH)
    result.player.farm.hands[0][0] = 99

    assert state.player.farm.hands == [[5, 4]]


# --- turns --------------------------------------------------------------


def test_farmer_and_every_hand_can_move_in_one_turn():
    state = _state(hands=[(5, 4), (4, 5)])
    turn = Turn(farmer=Action(NORTH), hands=(Action(EAST), Action(SOUTH)))

    result = Simulator().simulate_turn(state, turn)

    assert result.player.farm.farmer == [4, 3]
    assert result.player.farm.hands == [[6, 4], [4, 6]]


def test_turn_mixes_movement_and_planting_by_unit():
    state = _state(hands=[(3, 3)], seeds={"WHEAT": 1})
    turn = Turn(farmer=Action(WEST), hands=(Action(PLANT, "WHEAT"),))

    result = Simulator().simulate_turn(state, turn)

    assert result.player.farm.farmer == [3, 4]
    assert isinstance(result.player.farm.tiles[3][3], PlantTile)


def test_turn_with_an_off_board_move_is_rejected():
    state = _state(hands=[(0, 0)])
    turn = Turn(farmer=Action(NORTH), hands=(Action(WEST),))

    with pytest.raises(ValueError, match="off the board"):
        Simulator().simulate_turn(state, turn)


def test_movement_in_the_market_channel_is_rejected():
    with pytest.raises(ValueError, match="not a market action"):
        Simulator().simulate_turn(_state(), Turn(market=(Action(NORTH),)))


# --- Operator -----------------------------------------------------------


@pytest.mark.parametrize("direction", sorted(MOVEMENT_ACTION_TYPES))
def test_operator_writes_movement_as_bare_op(direction):
    assert Operator().to_unit_op(Action(direction)) == [direction]


def test_operator_writes_movement_for_farmer_and_hands():
    turn = Turn(farmer=Action(NORTH), hands=(Action(EAST), Action(PLANT, "WHEAT")))

    assert Operator().execute(Decision(turn)) == {
        "farmer": ["NORTH"],
        "hands": [["EAST"], ["PLANT", "WHEAT"]],
        "market": [],
    }


@pytest.mark.parametrize(
    "action", [Action(NORTH, target="WHEAT"), Action(SOUTH, quantity=2)]
)
def test_operator_rejects_malformed_movement(action):
    with pytest.raises(ValueError):
        Operator().to_unit_op(action)


def test_operator_rejects_movement_as_market_order():
    with pytest.raises(ValueError, match="Unsupported market action"):
        Operator().to_market_order(Action(WEST))


# --- Generator ----------------------------------------------------------


def test_generator_does_not_propose_movement_yet():
    actions = CandidateGenerator().generate(_state(hands=[(5, 4)]))

    assert not {action.action_type for action in actions} & MOVEMENT_ACTION_TYPES


# --- parity with the real environment ----------------------------------

# Farmer op, hand ops, and market orders submitted at each step. Two hands
# are hired at step 0 and spawn on shed-access tiles (5, 4) and (4, 5);
# (5, 4) is in the locked NE quadrant.
_ENV_PLAN = {
    0: (["PASS"], [], [["BUY_SEED", "WHEAT", 1], ["HIRE"], ["HIRE"]]),
    1: (["PLANT", "WHEAT"], [["EAST"], ["SOUTH"]], []),  # hands cross locked tiles
    2: (["EAST"], [["EAST"], ["NORTH"]], []),  # farmer onto a locked tile
    3: (["WEST"], [["WEST"], ["WEST"]], []),  # farmer back onto the planted tile
    4: (["SOUTH"], [["NORTH"], ["WEST"]], []),
    5: (["WEST"], [["WEST"], ["EAST"]], []),  # farmer and hand 2 both onto (3, 5)
}


def test_movement_matches_real_environment_steps():
    kaggle_environments = pytest.importorskip("kaggle_environments")
    received = {}

    def agent(obs):
        received[obs["step"]] = copy.deepcopy(dict(obs))
        farmer, hands, market = _ENV_PLAN.get(obs["step"], (["PASS"], [], []))
        return {"farmer": farmer, "hands": hands, "market": market}

    env = kaggle_environments.make(
        "kaggriculture", configuration={"episodeSteps": max(_ENV_PLAN) + 3}, debug=True
    )
    env.run([agent, "pass"])

    for step in range(1, max(_ENV_PLAN) + 1):
        farmer, hands, _ = _ENV_PLAN[step]
        before, after = parse(received[step]), parse(received[step + 1])
        turn = Turn(farmer=Action(*farmer), hands=tuple(Action(*op) for op in hands))

        predicted = Simulator().simulate_turn(before, turn)

        assert predicted.player == after.player, step

    final = parse(received[max(_ENV_PLAN) + 1]).player.farm
    assert final.farmer == final.hands[1] == [3, 5]


@pytest.mark.parametrize(
    ("position", "direction"),
    [([0, 0], "NORTH"), ([0, 0], "WEST"), ([9, 9], "SOUTH"), ([9, 9], "EAST")],
)
def test_environment_ignores_off_board_moves_that_the_simulator_rejects(position, direction):
    env = pytest.importorskip("kaggle_environments.envs.kaggriculture.kaggriculture")
    raw_farm = {"farmer": list(position), "hands": [list(position)], "tiles": [[None] * 10] * 10}
    private = {"inventories": [{}, {}], "shed": {}, "seeds": {}}

    for unit in (0, 1):
        env._apply_unit_action(raw_farm, private, unit, [direction], 10, 0, 24)

    assert raw_farm["farmer"] == position and raw_farm["hands"] == [position]
    state = _state(farmer=position, hands=[position])
    for unit in (0, 1):
        with pytest.raises(ValueError, match="off the board"):
            _move(state, direction, unit=unit)
