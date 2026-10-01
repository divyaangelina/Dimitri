"""Unit tests for the Executive's action selection."""

import copy
import dataclasses

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
from dimitri.planner.action import Action
from dimitri.planner.evaluation import Evaluation
from dimitri.planner.planner import Planner
from dimitri.planner.planning import CandidateEvaluation, PlanningResult
from dimitri.planner.turn import Turn


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


def _candidate(action: Action, objective_value: int) -> CandidateEvaluation:
    return CandidateEvaluation(
        turn=Turn.from_action(action),
        resulting_state=_make_game_state(),
        evaluation=Evaluation(
            cash=objective_value,
            inventory_value=0,
            seed_cost=0,
            final_objective_value=objective_value,
        ),
    )


def _only_action(turn: Turn) -> Action:
    (action,) = turn.actions()
    return action


def _result(*candidates: CandidateEvaluation) -> PlanningResult:
    return PlanningResult(candidates=tuple(candidates))


def test_selects_highest_final_objective_value():
    result = _result(
        _candidate(Action("BUY_PRODUCT", "WHEAT"), 100),
        _candidate(Action("SELL", "EGG"), 300),
        _candidate(Action("PLANT", "WHEAT"), 200),
    )

    assert _only_action(Executive().decide(result).turn) == Action("SELL", "EGG")


def test_returns_exact_action_object_from_winner():
    winner = Action("SELL", "EGG")
    result = _result(
        _candidate(Action("BUY_PRODUCT", "WHEAT"), 100),
        _candidate(winner, 300),
    )

    assert _only_action(Executive().decide(result).turn) is winner


def test_lower_valued_candidate_is_not_selected():
    lower = Action("BUY_PRODUCT", "WHEAT")
    higher = Action("BUY_PRODUCT", "EGG")
    result = _result(_candidate(lower, 150), _candidate(higher, 151))

    selected = _only_action(Executive().decide(result).turn)

    assert selected is higher
    assert selected is not lower


def test_equal_values_select_first_candidate():
    first = Action("BUY_PRODUCT", "WHEAT")
    result = _result(
        _candidate(Action("SELL", "EGG"), 100),
        _candidate(first, 200),
        _candidate(Action("PLANT", "WHEAT"), 200),
        _candidate(Action("BUY_PRODUCT", "EGG"), 200),
    )

    assert _only_action(Executive().decide(result).turn) is first


def test_equal_values_from_planner_select_first_candidate():
    # No money and an empty shed leave only PLANT candidates, none of
    # which changes cash.
    result = Planner().plan(
        _make_game_state(money=0, shed={}, seeds={"WHEAT": 3, "TOMATO": 1})
    )
    values = {c.evaluation.final_objective_value for c in result.candidates}

    assert len(result.candidates) > 1
    assert len(values) == 1
    assert Executive().decide(result).turn is result.candidates[0].turn


def test_ignores_inventory_value_when_selecting():
    richer_in_goods = Action("BUY_PRODUCT", "EGG")
    richer_in_cash = Action("SELL", "WHEAT")
    result = _result(
        CandidateEvaluation(
            turn=Turn.from_action(richer_in_goods),
            resulting_state=_make_game_state(),
            evaluation=Evaluation(
                cash=100, inventory_value=500, seed_cost=0, final_objective_value=100
            ),
        ),
        CandidateEvaluation(
            turn=Turn.from_action(richer_in_cash),
            resulting_state=_make_game_state(),
            evaluation=Evaluation(
                cash=150, inventory_value=0, seed_cost=0, final_objective_value=150
            ),
        ),
    )

    assert _only_action(Executive().decide(result).turn) is richer_in_cash


def test_planner_candidates_are_distinguished_by_resulting_cash():
    # Default state: money 100, shed WHEAT x2 and EGG x1, market inventory
    # WHEAT 10000 and EGG 9000. Environment quotes: buy WHEAT 26, sell
    # WHEAT 25, sell EGG 110.
    result = Planner().plan(_make_game_state())
    by_action = {
        _only_action(c.turn): c.evaluation for c in result.candidates if c.turn.actions()
    }

    assert by_action[Action("BUY_PRODUCT", "WHEAT")].final_objective_value == 74
    assert by_action[Action("SELL", "WHEAT")].final_objective_value == 125
    assert by_action[Action("PLANT", "WHEAT")].final_objective_value == 100
    assert _only_action(Executive().decide(result).turn) == Action("SELL", "EGG")


def test_selects_a_complete_turn():
    single = Turn.from_action(Action("SELL", "WHEAT"))
    complete = Turn(
        farmer=Action("PLANT", "WHEAT"),
        hands=(Action("PLANT", "TOMATO"),),
        market=(Action("SELL", "EGG"), Action("SELL", "WHEAT")),
    )

    def candidate(turn, value):
        return CandidateEvaluation(
            turn=turn,
            resulting_state=_make_game_state(),
            evaluation=Evaluation(
                cash=value, inventory_value=0, seed_cost=0, final_objective_value=value
            ),
        )

    decision = Executive().decide(_result(candidate(single, 125), candidate(complete, 165)))

    assert decision == Decision(turn=complete)
    assert decision.turn is complete


def test_selects_empty_turn_when_it_is_the_best_candidate():
    idle = Turn()
    buy = Turn.from_action(Action("BUY_PRODUCT", "WHEAT"))
    result = _result(
        CandidateEvaluation(
            turn=buy,
            resulting_state=_make_game_state(),
            evaluation=Evaluation(
                cash=75, inventory_value=25, seed_cost=0, final_objective_value=75
            ),
        ),
        CandidateEvaluation(
            turn=idle,
            resulting_state=_make_game_state(),
            evaluation=Evaluation(
                cash=100, inventory_value=0, seed_cost=0, final_objective_value=100
            ),
        ),
    )

    assert Executive().decide(result).turn is idle


def test_empty_planning_result_raises():
    with pytest.raises(ValueError, match="Cannot decide without candidate actions"):
        Executive().decide(PlanningResult(candidates=()))


def test_decide_does_not_mutate_planning_result():
    result = _result(
        _candidate(Action("BUY_PRODUCT", "WHEAT"), 100),
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

    assert _only_action(executive.decide(build()).turn) == _only_action(executive.decide(build()).turn)
    result = build()
    assert _only_action(executive.decide(result).turn) is _only_action(executive.decide(result).turn)


def test_selects_buy_action():
    buy = Action("BUY_PRODUCT", "EGG")
    result = _result(
        _candidate(Action("SELL", "WHEAT"), 100),
        _candidate(buy, 250),
        _candidate(Action("PLANT", "WHEAT"), 200),
    )

    assert _only_action(Executive().decide(result).turn) is buy


def test_selects_sell_action():
    sell = Action("SELL", "WHEAT")
    result = _result(
        _candidate(Action("BUY_PRODUCT", "EGG"), 100),
        _candidate(sell, 250),
        _candidate(Action("PLANT", "WHEAT"), 200),
    )

    assert _only_action(Executive().decide(result).turn) is sell


def test_selects_plant_action():
    plant = Action("PLANT", "TOMATO")
    result = _result(
        _candidate(Action("BUY_PRODUCT", "EGG"), 100),
        _candidate(Action("SELL", "WHEAT"), 200),
        _candidate(plant, 250),
    )

    assert _only_action(Executive().decide(result).turn) is plant


def test_decide_returns_immutable_decision():
    winner = Action("SELL", "EGG")
    decision = Executive().decide(_result(_candidate(winner, 100)))

    assert decision == Decision(turn=Turn.from_action(winner))
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.turn = Turn()


def test_decision_carries_only_the_selected_turn():
    assert {f.name for f in dataclasses.fields(Decision)} == {"turn"}
