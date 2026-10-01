"""Tests for the Planner -> Executive -> Operator decision pipeline.

Planner proposes. Executive decides. Operator executes. These tests
check each handoff and that no stage takes over another's role.
"""

import copy

import pytest

from dimitri.executive.decision import Decision
from dimitri.executive.executive import Executive
from dimitri.models.farm import Farm
from dimitri.models.game_state import GameState
from dimitri.models.inventory import Inventory
from dimitri.models.market import Market
from dimitri.models.opponent import Opponent
from dimitri.models.player import Player
from dimitri.models.town import Town
from dimitri.operator import operator as operator_module
from dimitri.operator.operator import Operator
from dimitri.planner.action import Action
from dimitri.planner.planner import Planner
from dimitri.planner.planning import CandidateEvaluation, PlanningResult
from dimitri.planner.turn import Turn

API_KEYS = {"farmer", "hands", "market"}


def _make_farm() -> Farm:
    return Farm(
        tiles=[[None, "LOCKED"], [{"type": "WHEAT"}, None]],
        farmer=[0, 0],
        hands=[[1, 1]],
        unlocked_quadrants=["NW"],
        hires_today=1,
    )


def _make_game_state() -> GameState:
    return GameState(
        step=79,
        day=3,
        hour=7,
        player=Player(
            player_id=0,
            money=100,
            inventory=Inventory(items={"WHEAT": 2, "EGG": 1}),
            seeds={"WHEAT": 3},
            farm=_make_farm(),
            unit_inventories=(Inventory(items={}),),
        ),
        opponent=Opponent(player_id=1, money=250, farm=_make_farm()),
        market=Market(
            prices={"WHEAT": 25, "EGG": 40},
            inventory={"WHEAT": 10000, "EGG": 9000},
        ),
        town=Town(unlocked_shops=()),
        raw_observation={"day": 3, "hour": 7},
    )


def _run_pipeline(game_state: GameState):
    planning_result = Planner().plan(game_state)
    decision = Executive().decide(planning_result)
    return planning_result, decision, Operator().execute(decision)


# --- handoffs ---


def test_planner_produces_candidate_options():
    result = Planner().plan(_make_game_state())

    assert isinstance(result, PlanningResult)
    assert len(result.candidates) > 1
    assert all(isinstance(c, CandidateEvaluation) for c in result.candidates)
    assert all(isinstance(c.turn, Turn) for c in result.candidates)
    assert all(isinstance(a, Action) for c in result.candidates for a in c.turn.actions())


def test_executive_receives_candidates_and_selects_one():
    planning_result = Planner().plan(_make_game_state())

    decision = Executive().decide(planning_result)

    assert isinstance(decision, Decision)
    candidate_turns = [c.turn for c in planning_result.candidates]
    assert sum(decision.turn is t for t in candidate_turns) == 1


def test_selected_decision_can_be_passed_to_operator():
    _, decision, api_action = _run_pipeline(_make_game_state())

    assert api_action == Operator().execute(decision)


def test_operator_converts_decision_to_kaggriculture_action():
    _, decision, api_action = _run_pipeline(_make_game_state())

    assert set(api_action) == API_KEYS
    (action,) = decision.turn.actions()
    if api_action["market"]:
        assert api_action == {
            "farmer": ["PASS"],
            "hands": [],
            "market": [[action.action_type, action.target, action.quantity]],
        }
    else:
        assert api_action == {
            "farmer": [action.action_type, action.target],
            "hands": [],
            "market": [],
        }


def test_pipeline_does_not_mutate_game_state():
    game_state = _make_game_state()
    before = copy.deepcopy(game_state)

    _run_pipeline(game_state)

    assert game_state == before


def test_pipeline_is_deterministic():
    assert _run_pipeline(_make_game_state()) == _run_pipeline(_make_game_state())


# --- responsibility boundaries ---


def test_planner_does_not_execute_actions():
    result = Planner().plan(_make_game_state())

    assert not isinstance(result, (Decision, dict))
    for obj in (Planner(), result):
        assert not any(hasattr(obj, name) for name in ("decide", "execute"))


def test_planner_output_cannot_be_executed_directly():
    result = Planner().plan(_make_game_state())

    with pytest.raises(TypeError):
        Operator().execute(result)
    with pytest.raises(TypeError):
        Operator().execute(result.candidates[0].turn)


def test_executive_does_not_execute_actions():
    decision = Executive().decide(Planner().plan(_make_game_state()))

    assert not isinstance(decision, dict)
    assert not hasattr(Executive(), "execute")
    assert not any(hasattr(decision, key) for key in API_KEYS)


def test_operator_does_not_make_decisions():
    operator = Operator()

    assert not any(
        hasattr(operator, name) for name in ("decide", "plan", "select", "rank")
    )
    # The Operator has no access to candidates, evaluations, or state.
    for name in ("PlanningResult", "CandidateEvaluation", "Evaluation", "GameState"):
        assert not hasattr(operator_module, name)
