"""Unit tests for the Executive's action selection."""

import copy

import pytest

from dimitri.executive.executive import Executive
from dimitri.models.farm import Farm
from dimitri.models.game_state import GameState
from dimitri.models.inventory import Inventory
from dimitri.models.market import Market
from dimitri.models.opponent import Opponent
from dimitri.models.player import Player
from dimitri.planner.action import Action
from dimitri.planner.evaluation import Evaluation
from dimitri.planner.planner import Planner
from dimitri.planner.planning import CandidateEvaluation, PlanningResult


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
        day=3,
        hour=7,
        player=Player(
            player_id=0,
            money=money,
            inventory=Inventory(items={"WHEAT": 2, "EGG": 1} if shed is None else shed),
            seeds={"WHEAT": 3, "TOMATO": 1} if seeds is None else seeds,
            farm=_make_farm(),
        ),
        opponent=Opponent(player_id=1, money=250, farm=_make_farm()),
        market=Market(
            prices={"WHEAT": 25, "EGG": 40, "TOMATO": 30} if prices is None else prices,
            inventory={"WHEAT": 10000, "EGG": 9000},
        ),
        raw_observation={"day": 3, "hour": 7},
    )


def _candidate(action: Action, total_liquid_value: int) -> CandidateEvaluation:
    return CandidateEvaluation(
        action=action,
        resulting_state=_make_game_state(),
        evaluation=Evaluation(
            cash=total_liquid_value,
            inventory_value=0,
            seed_cost=0,
            total_liquid_value=total_liquid_value,
        ),
    )


def _result(*candidates: CandidateEvaluation) -> PlanningResult:
    return PlanningResult(candidates=tuple(candidates))


def test_selects_highest_total_liquid_value():
    result = _result(
        _candidate(Action("BUY", "WHEAT"), 100),
        _candidate(Action("SELL", "EGG"), 300),
        _candidate(Action("PLANT", "WHEAT"), 200),
    )

    assert Executive().decide(result) == Action("SELL", "EGG")


def test_returns_exact_action_object_from_winner():
    winner = Action("SELL", "EGG")
    result = _result(
        _candidate(Action("BUY", "WHEAT"), 100),
        _candidate(winner, 300),
    )

    assert Executive().decide(result) is winner


def test_lower_valued_candidate_is_not_selected():
    lower = Action("BUY", "WHEAT")
    higher = Action("BUY", "EGG")
    result = _result(_candidate(lower, 150), _candidate(higher, 151))

    decision = Executive().decide(result)

    assert decision is higher
    assert decision is not lower


def test_equal_values_select_first_candidate():
    first = Action("BUY", "WHEAT")
    result = _result(
        _candidate(Action("SELL", "EGG"), 100),
        _candidate(first, 200),
        _candidate(Action("PLANT", "WHEAT"), 200),
        _candidate(Action("BUY", "EGG"), 200),
    )

    assert Executive().decide(result) is first


def test_equal_values_from_planner_select_first_candidate():
    result = Planner().plan(_make_game_state())
    values = {c.evaluation.total_liquid_value for c in result.candidates}

    assert len(result.candidates) > 1
    assert len(values) == 1
    assert Executive().decide(result) is result.candidates[0].action


def test_empty_planning_result_raises():
    with pytest.raises(ValueError, match="Cannot decide without candidate actions"):
        Executive().decide(PlanningResult(candidates=()))


def test_decide_does_not_mutate_planning_result():
    result = _result(
        _candidate(Action("BUY", "WHEAT"), 100),
        _candidate(Action("SELL", "EGG"), 300),
    )
    candidates_before = result.candidates
    before = copy.deepcopy(result)

    Executive().decide(result)

    assert result == before
    assert result.candidates is candidates_before


def test_decide_does_not_mutate_game_states():
    game_state = _make_game_state()
    result = Planner().plan(game_state)
    game_state_before = copy.deepcopy(game_state)
    resulting_before = copy.deepcopy([c.resulting_state for c in result.candidates])

    Executive().decide(result)

    assert game_state == game_state_before
    assert [c.resulting_state for c in result.candidates] == resulting_before


def test_repeated_decisions_are_identical():
    def build():
        return Planner().plan(_make_game_state(prices={"WHEAT": 25, "EGG": 40}))

    executive = Executive()

    assert executive.decide(build()) == executive.decide(build())
    result = build()
    assert executive.decide(result) is executive.decide(result)


def test_selects_buy_action():
    buy = Action("BUY", "EGG")
    result = _result(
        _candidate(Action("SELL", "WHEAT"), 100),
        _candidate(buy, 250),
        _candidate(Action("PLANT", "WHEAT"), 200),
    )

    assert Executive().decide(result) is buy


def test_selects_sell_action():
    sell = Action("SELL", "WHEAT")
    result = _result(
        _candidate(Action("BUY", "EGG"), 100),
        _candidate(sell, 250),
        _candidate(Action("PLANT", "WHEAT"), 200),
    )

    assert Executive().decide(result) is sell


def test_selects_plant_action():
    plant = Action("PLANT", "TOMATO")
    result = _result(
        _candidate(Action("BUY", "EGG"), 100),
        _candidate(Action("SELL", "WHEAT"), 200),
        _candidate(plant, 250),
    )

    assert Executive().decide(result) is plant
