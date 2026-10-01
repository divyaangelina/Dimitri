"""End-to-end tests for the full Dimitri pipeline.

    observation -> Observer -> GameState -> Analyst -> Analysis
                -> Planner -> candidates -> Executive -> Decision
                -> Operator -> Kaggriculture action

Each layer is the real implementation, wrapped only to record what it
received and returned, so the tests can confirm every handoff happens
through the layer that owns it and none is bypassed.
"""

import copy
import json
from pathlib import Path

import pytest

from dimitri.analyst.analysis import Analysis
from dimitri.analyst.analyst import Analyst
from dimitri.executive.decision import Decision
from dimitri.executive.executive import Executive
from dimitri.models.game_state import GameState
from dimitri.observer.observer import Observer
from dimitri.observer.parser import ParseError
from dimitri.observer.validator import ValidationError
from dimitri.operator.operator import Operator
from dimitri.pipeline import Pipeline
from dimitri.planner.planner import Planner
from dimitri.planner.planning import PlanningResult

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"
API_KEYS = {"farmer", "hands", "market"}


def _load_sample_observation() -> dict:
    with SAMPLE_OBSERVATION_PATH.open() as f:
        return json.load(f)


def _record(layer, method_name: str, calls: list):
    """Wrap ``layer.method_name`` so each call appends (name, arg, result)."""
    original = getattr(layer, method_name)

    def wrapper(arg):
        result = original(arg)
        calls.append((method_name, arg, result))
        return result

    setattr(layer, method_name, wrapper)
    return layer


def _recording_pipeline(calls: list) -> Pipeline:
    return Pipeline(
        observer=_record(Observer(), "observe", calls),
        analyst=_record(Analyst(), "analyze", calls),
        planner=_record(Planner(), "plan", calls),
        executive=_record(Executive(), "decide", calls),
        operator=_record(Operator(), "execute", calls),
    )


# --- successful end-to-end execution ---


def test_sample_observation_flows_through_every_layer():
    observation = _load_sample_observation()
    calls = []

    api_action = _recording_pipeline(calls).run(observation)

    assert [name for name, _, _ in calls] == [
        "observe",
        "analyze",
        "plan",
        "decide",
        "execute",
    ]
    (_, obs_in, game_state), (_, analyst_in, analysis), (_, planner_in, planning), (
        _,
        executive_in,
        decision,
    ), (_, operator_in, operator_out) = calls

    assert obs_in is observation
    assert isinstance(game_state, GameState)
    assert analyst_in is game_state
    assert isinstance(analysis, Analysis)
    assert planner_in is game_state
    assert isinstance(planning, PlanningResult)
    assert planning.candidates
    assert executive_in is planning
    assert isinstance(decision, Decision)
    assert any(decision.turn is c.turn for c in planning.candidates)
    assert operator_in is decision
    assert api_action is operator_out


def test_sample_observation_produces_kaggriculture_action():
    api_action = Pipeline().run(_load_sample_observation())

    assert set(api_action) == API_KEYS
    assert all(isinstance(api_action[key], list) for key in API_KEYS)
    # Every available purchase lowers cash, so waiting is the best candidate.
    assert api_action == {"farmer": ["PASS"], "hands": [], "market": []}


def test_pipeline_does_not_mutate_observation():
    observation = _load_sample_observation()
    before = copy.deepcopy(observation)

    Pipeline().run(observation)

    assert observation == before


def test_pipeline_is_deterministic():
    observation = _load_sample_observation()

    assert Pipeline().run(observation) == Pipeline().run(observation)


# --- no available actions ---


def _observation_without_actions() -> dict:
    """No money, empty shed, no seeds: nothing to buy, sell, or plant."""
    observation = _load_sample_observation()
    observation["farms"][observation["player"]]["money"] = 0
    return observation


def test_no_available_actions_passes_the_turn_through_the_executive():
    calls = []

    api_action = _recording_pipeline(calls).run(_observation_without_actions())

    assert api_action == {"farmer": ["PASS"], "hands": [], "market": []}
    (planning,) = [result for name, _, result in calls if name == "plan"]
    assert [c.turn.actions() for c in planning.candidates] == [()]
    # The idle turn is decided and executed like any other candidate.
    assert [name for name, _, _ in calls] == [
        "observe",
        "analyze",
        "plan",
        "decide",
        "execute",
    ]


# --- malformed input ---


def test_missing_field_raises_parse_error():
    observation = _load_sample_observation()
    del observation["market"]

    with pytest.raises(ParseError):
        Pipeline().run(observation)


def test_non_dict_observation_raises_parse_error():
    with pytest.raises(ParseError):
        Pipeline().run([])


def test_invalid_game_state_raises_validation_error():
    observation = _load_sample_observation()
    observation["day"] = "not-an-int"  # parses, but fails validation

    with pytest.raises(ValidationError):
        Pipeline().run(observation)


def test_malformed_input_stops_before_downstream_layers():
    observation = _load_sample_observation()
    del observation["market"]
    calls = []

    with pytest.raises(ParseError):
        _recording_pipeline(calls).run(observation)

    assert calls == []
