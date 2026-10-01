"""Tests for the idle turn: doing nothing as a first-class planning candidate.

Every planning pass includes the idle turn, in which the farmer and each
known hand PASS and no market order is placed. It is simulated,
evaluated, and selected exactly like any other candidate.
"""

import copy
import json
from pathlib import Path

import pytest

from dimitri.executive.decision import Decision
from dimitri.executive.executive import Executive
from dimitri.observer.parser import parse
from dimitri.operator.operator import Operator
from dimitri.pipeline import Pipeline
from dimitri.planner.action import BUY_PRODUCT, BUY_SEED
from dimitri.planner.evaluator import Evaluator
from dimitri.planner.generator import CandidateGenerator
from dimitri.planner.planner import Planner, idle_turn
from dimitri.planner.planning import PlanningResult
from dimitri.planner.turn import Turn

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"
IDLE_API_ACTION = {"farmer": ["PASS"], "hands": [], "market": []}


def _observation(*, money=None, shed=None, seeds=None, hands=()):
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)
    farm = observation["farms"][observation["player"]]
    if money is not None:
        farm["money"] = money
    farm["hands"] = [list(h) for h in hands]
    private = observation["private"]
    if shed is not None:
        private["shed"] = shed
    if seeds is not None:
        private["seeds"] = seeds
    private["inventories"] = [{} for _ in range(1 + len(hands))]
    return observation


def _state(**kwargs):
    return parse(_observation(**kwargs))


def _idle_candidates(result):
    return [c for c in result.candidates if not c.turn.actions()]


class _EmptyGenerator(CandidateGenerator):
    def generate(self, game_state):
        return ()


# --- the Planner always includes the idle turn ---------------------------


def test_idle_turn_is_empty_without_hands():
    assert idle_turn(_state()) == Turn()


def test_idle_turn_passes_every_known_hand():
    turn = idle_turn(_state(hands=[(4, 4), (5, 5)]))

    assert turn == Turn(hands=(None, None))
    assert turn.actions() == ()


def test_planner_includes_idle_turn_alongside_actions():
    game_state = _state(money=3000)

    result = Planner().plan(game_state)

    assert len(result.candidates) > 1
    assert [c.turn for c in _idle_candidates(result)] == [Turn()]


def test_planner_includes_idle_turn_when_no_action_is_available():
    game_state = _state(money=0, shed={}, seeds={})

    result = Planner().plan(game_state)

    assert [c.turn for c in result.candidates] == [Turn()]


def test_planner_includes_idle_turn_with_an_empty_generator():
    game_state = _state(hands=[(4, 4)])

    result = Planner(generator=_EmptyGenerator()).plan(game_state)

    assert [c.turn for c in result.candidates] == [Turn(hands=(None,))]


# --- the idle turn is simulated and evaluated ----------------------------


def test_idle_turn_leaves_game_state_unchanged():
    game_state = _state(money=3000, hands=[(4, 4)])

    (idle,) = _idle_candidates(Planner().plan(game_state))

    assert idle.resulting_state == game_state
    assert idle.resulting_state is not game_state


def test_idle_turn_is_evaluated_at_current_cash():
    game_state = _state(money=3000)

    (idle,) = _idle_candidates(Planner().plan(game_state))

    assert idle.evaluation == Evaluator().evaluate(game_state)
    assert idle.evaluation.final_objective_value == 3000


def test_planning_does_not_mutate_game_state():
    game_state = _state(money=3000, hands=[(4, 4)])
    before = copy.deepcopy(game_state)

    Planner().plan(game_state)

    assert game_state == before


# --- the Executive can select the idle turn ------------------------------


def test_idle_turn_wins_when_every_action_reduces_cash():
    # Money and an empty shed with no seeds: only purchases are available.
    game_state = _state(money=3000, shed={}, seeds={})
    result = Planner().plan(game_state)
    actionable = [c for c in result.candidates if c.turn.actions()]

    assert actionable
    assert {c.turn.market[0].action_type for c in actionable} == {BUY_PRODUCT, BUY_SEED}
    assert all(c.evaluation.final_objective_value < 3000 for c in actionable)
    assert Executive().decide(result) == Decision(turn=Turn())


def test_action_still_wins_when_it_increases_cash():
    game_state = _state(money=3000, shed={"EGG": 1}, seeds={})

    decision = Executive().decide(Planner().plan(game_state))

    assert decision.turn.actions() != ()


# --- the Pipeline has no separate no-candidate path ----------------------


class _NoCandidatePlanner(Planner):
    def plan(self, game_state):
        return PlanningResult(candidates=())


def test_pipeline_always_consults_the_executive():
    # Without the old shortcut, an empty PlanningResult reaches the
    # Executive, which refuses it, instead of being turned into a PASS.
    with pytest.raises(ValueError, match="Cannot decide"):
        Pipeline(planner=_NoCandidatePlanner()).run(_observation())


def test_pipeline_idle_output_without_hands():
    observation = _observation(money=0, shed={}, seeds={})

    assert Pipeline().run(observation) == IDLE_API_ACTION


def test_pipeline_idle_output_passes_every_known_hand():
    observation = _observation(money=0, shed={}, seeds={}, hands=[(4, 4), (5, 5)])

    assert Pipeline().run(observation) == {
        "farmer": ["PASS"],
        "hands": [["PASS"], ["PASS"]],
        "market": [],
    }


def test_operator_writes_idle_turn_with_pass_per_hand():
    game_state = _state(hands=[(4, 4)])

    api_action = Operator().execute(Decision(turn=idle_turn(game_state)))

    assert api_action == {"farmer": ["PASS"], "hands": [["PASS"]], "market": []}


# --- the real environment ------------------------------------------------


def test_real_environment_passes_when_every_action_loses_cash():
    kaggle_environments = pytest.importorskip("kaggle_environments")
    pipeline = Pipeline()
    observed, sent = {}, {}

    def agent(obs):
        obs = copy.deepcopy(dict(obs))
        observed[obs["step"]] = obs
        if obs["step"] == 0:
            # Scripted setup: hire one hand so the idle turn has a hand to PASS.
            action = {"farmer": ["PASS"], "hands": [], "market": [["HIRE"]]}
        else:
            action = pipeline.run(obs)
        sent[obs["step"]] = action
        return action

    env = kaggle_environments.make(
        "kaggriculture", configuration={"episodeSteps": 5}, debug=True
    )
    env.run([agent, "pass"])

    for step in (1, 2):
        before, after = parse(observed[step]), parse(observed[step + 1])
        planning = Planner().plan(before)
        actionable = [c for c in planning.candidates if c.turn.actions()]

        # Only purchases are available at the start, and each lowers cash.
        assert actionable
        assert all(
            c.evaluation.final_objective_value < before.player.money
            for c in actionable
        )
        assert len(before.player.farm.hands) == 1
        assert sent[step] == {"farmer": ["PASS"], "hands": [["PASS"]], "market": []}
        # The environment applied the PASS: nothing about the player changed.
        assert after.player == before.player
