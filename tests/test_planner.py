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
from dimitri.planner.action import Action
from dimitri.planner.evaluator import Evaluator
from dimitri.planner.generator import CandidateGenerator
from dimitri.planner.planner import Planner
from dimitri.planner.planning import CandidateEvaluation, PlanningResult
from dimitri.planner.simulator import Simulator


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


class _RecordingSimulator(Simulator):
    """A Simulator that records the state each simulation started from."""

    def __init__(self):
        self.inputs = []

    def simulate(self, game_state, action):
        self.inputs.append(game_state)
        return super().simulate(game_state, action)


class _EmptyGenerator(CandidateGenerator):
    def generate(self, game_state):
        return ()


def test_plan_returns_planning_result():
    assert isinstance(Planner().plan(_make_game_state()), PlanningResult)


def test_every_candidate_receives_exactly_one_evaluation():
    game_state = _make_game_state()
    actions = CandidateGenerator().generate(game_state)

    result = Planner().plan(game_state)

    evaluated = [c.action for c in result.candidates]
    assert all(isinstance(c, CandidateEvaluation) for c in result.candidates)
    assert all(evaluated.count(action) == 1 for action in actions)


def test_candidate_count_matches_generated_count():
    game_state = _make_game_state()
    actions = CandidateGenerator().generate(game_state)

    result = Planner().plan(game_state)

    assert len(actions) > 1
    assert len(result.candidates) == len(actions)


def test_candidate_order_is_preserved():
    game_state = _make_game_state()

    result = Planner().plan(game_state)

    assert tuple(c.action for c in result.candidates) == (
        CandidateGenerator().generate(game_state)
    )


def test_candidate_action_matches_generated_action():
    game_state = _make_game_state()
    actions = CandidateGenerator().generate(game_state)

    result = Planner().plan(game_state)

    for action, candidate in zip(actions, result.candidates, strict=True):
        assert candidate.action == action


def test_resulting_state_corresponds_to_action():
    game_state = _make_game_state()

    result = Planner().plan(game_state)

    for candidate in result.candidates:
        assert candidate.resulting_state == Simulator().simulate(
            game_state, candidate.action
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
    buys = {
        c.action.target: c.resulting_state.player.money
        for c in result.candidates
        if c.action.action_type == "BUY"
    }

    assert buys == {"WHEAT": 75, "EGG": 60}


def test_plan_does_not_mutate_game_state():
    game_state = _make_game_state()
    before = copy.deepcopy(game_state)

    Planner().plan(game_state)

    assert game_state == before


def test_empty_candidate_set_produces_empty_result():
    result = Planner(generator=_EmptyGenerator()).plan(_make_game_state())

    assert result == PlanningResult(candidates=())


def test_no_available_actions_produces_empty_result():
    game_state = _make_game_state(money=0, shed={}, seeds={})

    assert Planner().plan(game_state) == PlanningResult(candidates=())


def test_planning_result_is_immutable():
    result = Planner().plan(_make_game_state())

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.candidates = ()


def test_candidate_evaluation_is_immutable():
    candidate = Planner().plan(_make_game_state()).candidates[0]

    with pytest.raises(dataclasses.FrozenInstanceError):
        candidate.action = Action("BUY", "EGG")


def test_identical_states_produce_identical_results():
    assert Planner().plan(_make_game_state()) == Planner().plan(_make_game_state())


def test_planner_exposes_no_selection():
    forbidden = {"selected_action", "best_action", "winner", "recommendation", "ranking"}
    result = Planner().plan(_make_game_state())

    assert {f.name for f in dataclasses.fields(PlanningResult)} == {"candidates"}
    assert {f.name for f in dataclasses.fields(CandidateEvaluation)} == {
        "action",
        "resulting_state",
        "evaluation",
    }
    for obj in (Planner(), result):
        assert not any(hasattr(obj, name) for name in forbidden)
