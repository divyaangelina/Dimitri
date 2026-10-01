"""Tests for hands that PASS while other units act.

A hand that does nothing this turn is None in ``Turn.hands``. The
installed Kaggriculture environment reads hand ops by position
(``hands_actions[h_idx]`` drives hand ``h_idx + 1``) and treats
``["PASS"]`` as a no-op in ``_apply_unit_action``, so the Operator must
keep a ``["PASS"]`` slot for every passing hand.
"""

import copy
import dataclasses
import json
from pathlib import Path

import pytest

from dimitri.executive.decision import Decision
from dimitri.observer.parser import parse
from dimitri.operator.operator import Operator
from dimitri.planner.action import EAST, NORTH, PLANT, SELL, SOUTH, WEST, Action
from dimitri.planner.simulator import Simulator
from dimitri.planner.turn import Turn

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"


def _state(*, farmer=(4, 4), hands=()):
    """A parsed GameState from the sample observation (10x10 board, NW unlocked)."""
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)
    farm = observation["farms"][0]
    farm["farmer"] = list(farmer)
    farm["hands"] = [list(h) for h in hands]
    observation["private"]["inventories"] = [{} for _ in range(1 + len(hands))]
    return parse(observation)


def _execute(turn):
    return Operator().execute(Decision(turn=turn))


# --- representation ------------------------------------------------------


def test_hand_can_pass_while_another_moves():
    turn = Turn(hands=(None, Action(NORTH)))

    assert turn.hands == (None, Action(NORTH))
    assert turn.actions() == (Action(NORTH),)


def test_multiple_hands_can_pass():
    turn = Turn(hands=(None, None, Action(EAST), None))

    assert turn.hands == (None, None, Action(EAST), None)
    assert turn.actions() == (Action(EAST),)


def test_every_hand_can_pass():
    turn = Turn(hands=(None, None))

    assert turn.hands == (None, None)
    assert turn.actions() == ()


def test_farmer_can_act_while_hands_pass():
    farmer = Action(PLANT, "WHEAT")

    turn = Turn(farmer=farmer, hands=(None, Action(SOUTH)))

    assert turn.actions() == (farmer, Action(SOUTH))


def test_hands_list_is_stored_as_tuple():
    turn = Turn(hands=[None, Action(NORTH)])

    assert turn.hands == (None, Action(NORTH))
    assert isinstance(turn.hands, tuple)
    assert turn == Turn(hands=(None, Action(NORTH)))


def test_turn_with_passing_hand_is_immutable_and_hashable():
    turn = Turn(hands=(None, Action(NORTH)))

    with pytest.raises(dataclasses.FrozenInstanceError):
        turn.hands = ()
    assert hash(turn) == hash(Turn(hands=(None, Action(NORTH))))


@pytest.mark.parametrize("entry", ["PASS", ["NORTH"], ("PASS",), 0, {}])
def test_malformed_hand_entry_is_rejected(entry):
    with pytest.raises(TypeError, match=r"Turn.hands\[1\]"):
        Turn(hands=(Action(NORTH), entry))


@pytest.mark.parametrize("hands", ["NORTH", Action(NORTH), None, {Action(NORTH)}])
def test_hands_must_be_a_sequence_of_entries(hands):
    with pytest.raises(TypeError, match="Turn.hands must be"):
        Turn(hands=hands)


# --- Operator ------------------------------------------------------------


def test_operator_writes_passing_hand_as_pass_slot():
    result = _execute(Turn(hands=(None, Action(NORTH))))

    assert result == {"farmer": ["PASS"], "hands": [["PASS"], ["NORTH"]], "market": []}


def test_operator_writes_every_passing_hand():
    result = _execute(Turn(hands=(None, None, Action(WEST))))

    assert result["hands"] == [["PASS"], ["PASS"], ["WEST"]]


def test_operator_writes_all_hands_passing():
    result = _execute(Turn(hands=(None, None)))

    assert result == {"farmer": ["PASS"], "hands": [["PASS"], ["PASS"]], "market": []}


def test_operator_writes_farmer_acting_while_hands_pass():
    turn = Turn(
        farmer=Action(PLANT, "WHEAT"),
        hands=(Action(EAST), None),
        market=(Action(SELL, "EGG", 1),),
    )

    assert _execute(turn) == {
        "farmer": ["PLANT", "WHEAT"],
        "hands": [["EAST"], ["PASS"]],
        "market": [["SELL", "EGG", 1]],
    }


def test_operator_compose_accepts_passing_hands():
    assert Operator().compose(hands=[Action(NORTH), None])["hands"] == [
        ["NORTH"],
        ["PASS"],
    ]


# --- Simulator -----------------------------------------------------------


def test_simulator_leaves_passing_hand_in_place():
    state = _state(hands=[(4, 4), (5, 5)])

    result = Simulator().simulate_turn(state, Turn(hands=(None, Action(NORTH))))

    assert result.player.farm.hands == [[4, 4], [5, 4]]
    assert result.player.farm.farmer == [4, 4]


def test_simulator_moves_only_the_acting_hands():
    state = _state(hands=[(1, 1), (2, 2), (3, 3)])
    turn = Turn(farmer=Action(EAST), hands=(Action(SOUTH), None, None))

    result = Simulator().simulate_turn(state, turn)

    assert result.player.farm.farmer == [5, 4]
    assert result.player.farm.hands == [[1, 2], [2, 2], [3, 3]]


def test_simulator_all_hands_passing_leaves_state_unchanged():
    state = _state(hands=[(1, 1), (2, 2)])

    result = Simulator().simulate_turn(state, Turn(hands=(None, None)))

    assert result == state
    assert result is not state


def test_simulator_all_hands_acting_is_unchanged_behavior():
    state = _state(hands=[(1, 1), (2, 2)])
    turn = Turn(hands=(Action(NORTH), Action(WEST)))

    result = Simulator().simulate_turn(state, turn)

    assert result.player.farm.hands == [[1, 0], [1, 2]]


def test_simulator_with_passing_hand_does_not_mutate_original():
    state = _state(hands=[(1, 1), (2, 2)])
    before = copy.deepcopy(state)

    Simulator().simulate_turn(state, Turn(hands=(None, Action(NORTH))))

    assert state == before


# --- the real environment ----------------------------------------------


def test_operator_pass_slot_matches_environment_hand_processing():
    env = pytest.importorskip("kaggle_environments.envs.kaggriculture.kaggriculture")
    hands = [(1, 1), (2, 2), (3, 3)]
    turn = Turn(hands=(None, Action(NORTH), None))
    raw_farm = {
        "farmer": [4, 4],
        "hands": [list(h) for h in hands],
        "tiles": [[None] * 10 for _ in range(10)],
    }
    private = {"inventories": [{} for _ in range(4)], "shed": {}, "seeds": {}}

    # Mirrors the environment's interpreter: hand op h_idx drives unit h_idx + 1.
    for h_idx, op in enumerate(_execute(turn)["hands"]):
        env._apply_unit_action(raw_farm, private, h_idx + 1, op, 10, 0, 24)

    predicted = Simulator().simulate_turn(_state(hands=hands), turn)
    assert raw_farm["hands"] == [[1, 1], [2, 1], [3, 3]]
    assert predicted.player.farm.hands == raw_farm["hands"]
