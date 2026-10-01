"""Unit tests for the Planner's candidate evaluation pipeline."""

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
from dimitri.planner.action import Action
from dimitri.planner.evaluator import Evaluator
from dimitri.planner.generator import CandidateGenerator
from dimitri.planner.planner import Planner, idle_turn
from dimitri.planner.planning import CandidateEvaluation, PlanningResult
from dimitri.planner.simulator import Simulator
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


class _RecordingSimulator(Simulator):
    """A Simulator that records the state each simulation started from."""

    def __init__(self):
        self.inputs = []

    def simulate_turn(self, game_state, turn):
        self.inputs.append(game_state)
        return super().simulate_turn(game_state, turn)


class _EmptyGenerator(CandidateGenerator):
    def generate(self, game_state):
        return ()


def test_plan_returns_planning_result():
    assert isinstance(Planner().plan(_make_game_state()), PlanningResult)


def test_every_candidate_receives_exactly_one_evaluation():
    game_state = _make_game_state()
    actions = CandidateGenerator().generate(game_state)

    result = Planner().plan(game_state)

    evaluated = [c.turn for c in result.candidates]
    assert all(isinstance(c, CandidateEvaluation) for c in result.candidates)
    assert all(evaluated.count(Turn.from_action(action)) == 1 for action in actions)


def test_candidate_count_matches_generated_count():
    game_state = _make_game_state()
    actions = CandidateGenerator().generate(game_state)

    result = Planner().plan(game_state)

    assert len(actions) > 1
    # One candidate per generated action, plus the idle turn.
    assert len(result.candidates) == len(actions) + 1


def test_candidate_order_is_preserved():
    game_state = _make_game_state()

    result = Planner().plan(game_state)

    assert tuple(c.turn for c in result.candidates) == (
        *(Turn.from_action(a) for a in CandidateGenerator().generate(game_state)),
        idle_turn(game_state),
    )


def test_candidate_turn_contains_only_the_generated_action():
    game_state = _make_game_state()
    actions = CandidateGenerator().generate(game_state)

    result = Planner().plan(game_state)

    for action, candidate in zip(actions, result.candidates[:-1], strict=True):
        assert candidate.turn == Turn.from_action(action)
        assert candidate.turn.actions() == (action,)


def test_resulting_state_corresponds_to_turn():
    game_state = _make_game_state()

    result = Planner().plan(game_state)

    for candidate in result.candidates:
        assert candidate.resulting_state == Simulator().simulate_turn(
            game_state, candidate.turn
        )


def test_evaluation_corresponds_to_resulting_state():
    result = Planner().plan(_make_game_state())

    for candidate in result.candidates:
        assert candidate.evaluation == Evaluator().evaluate(candidate.resulting_state)


def test_every_candidate_is_simulated_from_the_original_state():
    game_state = _make_game_state()
    simulator = _RecordingSimulator()

    result = Planner(simulator=simulator).plan(game_state)

    assert len(simulator.inputs) == len(result.candidates)
    assert all(state is game_state for state in simulator.inputs)


def test_candidate_simulations_do_not_accumulate():
    game_state = _make_game_state(money=100, prices={"WHEAT": 25, "EGG": 40})

    result = Planner().plan(game_state)
    trades = {
        (c.turn.market[0].action_type, c.turn.market[0].target): c.resulting_state.player.money
        for c in result.candidates
        if c.turn.market
    }

    # Each trade starts from money 100 (EGG is not buyable in Kaggriculture;
    # STRAWBERRY seed costs exactly 100).
    assert trades == {
        ("BUY_PRODUCT", "WHEAT"): 100 - 26,
        ("BUY_SEED", "WHEAT"): 100 - 10,
        ("BUY_SEED", "CARROT"): 100 - 20,
        ("BUY_SEED", "TOMATO"): 100 - 50,
        ("BUY_SEED", "STRAWBERRY"): 100 - 100,
        ("BUY_SEED", "MELON"): 100 - 80,
        ("SELL", "WHEAT"): 100 + 25,
        ("SELL", "EGG"): 100 + 110,
    }


def test_plan_does_not_mutate_game_state():
    game_state = _make_game_state()
    before = copy.deepcopy(game_state)

    Planner().plan(game_state)

    assert game_state == before


def test_empty_candidate_set_produces_only_the_idle_turn():
    game_state = _make_game_state()

    result = Planner(generator=_EmptyGenerator()).plan(game_state)

    assert [c.turn for c in result.candidates] == [idle_turn(game_state)]


def test_no_available_actions_produces_only_the_idle_turn():
    game_state = _make_game_state(money=0, shed={}, seeds={})

    result = Planner().plan(game_state)

    assert [c.turn for c in result.candidates] == [idle_turn(game_state)]


def test_planning_result_is_immutable():
    result = Planner().plan(_make_game_state())

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.candidates = ()


def test_candidate_evaluation_is_immutable():
    candidate = Planner().plan(_make_game_state()).candidates[0]

    with pytest.raises(dataclasses.FrozenInstanceError):
        candidate.turn = Turn.from_action(Action("BUY_PRODUCT", "EGG"))


def test_identical_states_produce_identical_results():
    assert Planner().plan(_make_game_state()) == Planner().plan(_make_game_state())


def test_planner_exposes_no_selection():
    forbidden = {"selected_action", "best_action", "winner", "recommendation", "ranking"}
    result = Planner().plan(_make_game_state())

    assert {f.name for f in dataclasses.fields(PlanningResult)} == {"candidates"}
    assert {f.name for f in dataclasses.fields(CandidateEvaluation)} == {
        "turn",
        "resulting_state",
        "evaluation",
    }
    for obj in (Planner(), result):
        assert not any(hasattr(obj, name) for name in forbidden)
