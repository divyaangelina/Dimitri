"""Tests that simulation keeps raw_observation isolated while not duplicating it needlessly.

Within one Simulator call, the intermediate states share the input's
raw_observation instead of each deep-copying it; only the state a public
method returns gets its own copy. These tests check the behavior callers
rely on: simulation never changes the original state or its observation,
and a returned state's data, raw_observation included, can be changed
without affecting the original or any other result.

The parser keeps some farm lists shared with the raw observation (the
farmer position, hands, and unlocked quadrants), so simulated moves are
checked against the observation dict itself as well.
"""

import copy
import json
from pathlib import Path

import pytest

from dimitri.analyst.opportunity import Opportunity, OpportunityKind
from dimitri.models.game_state import GameState
from dimitri.observer.parser import parse
from dimitri.observer.validator import validate
from dimitri.planner.action import BUY_SEED, NORTH, PLANT, WATER, Action
from dimitri.planner.continuation import ContinuationEvaluator
from dimitri.planner.plan import Plan
from dimitri.planner.plan_generator import WheatPlanGenerator
from dimitri.planner.simulator import Simulator
from dimitri.planner.turn import Turn

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"
WHEAT = Opportunity(OpportunityKind.WHEAT_PRODUCTION)


def _observation(step=0):
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)
    observation["step"] = step
    observation["day"], observation["hour"] = divmod(step, 24)
    return observation


def _plan(*turns):
    return Plan(WHEAT, turns=turns, horizon=len(turns))


_BUY = Turn(market=(Action(BUY_SEED, "WHEAT", 1),))
_PLANT = Turn(farmer=Action(PLANT, "WHEAT"))
_WATER = Turn(farmer=Action(WATER))


def _each_public_call(state):
    """Every public Simulator call, as (name, result)."""
    simulator = Simulator()
    return [
        ("simulate", simulator.simulate(state, Action(NORTH))),
        ("simulate_turn", simulator.simulate_turn(state, _BUY)),
        ("advance_turn", simulator.advance_turn(state)),
        ("play_turn", simulator.play_turn(state, Turn(farmer=Action(NORTH)))),
        ("simulate_plan", simulator.simulate_plan(state, _plan(_BUY, _PLANT, _WATER, *[Turn()] * 30))),
        ("empty plan", simulator.simulate_plan(state, _plan())),
    ]


# --- the original is never changed --------------------------------------


def test_simulating_a_plan_does_not_mutate_the_original():
    observation = _observation()
    state = parse(observation)
    snapshot, observation_snapshot = copy.deepcopy(state), copy.deepcopy(observation)

    Simulator().simulate_plan(state, _plan(_BUY, _PLANT, _WATER, *[Turn()] * 60))

    assert state == snapshot
    assert observation == observation_snapshot


def test_simulating_a_turn_does_not_mutate_the_original():
    observation = _observation()
    state = parse(observation)
    snapshot, observation_snapshot = copy.deepcopy(state), copy.deepcopy(observation)

    Simulator().simulate_turn(state, Turn(farmer=Action(NORTH), market=_BUY.market))

    assert state == snapshot
    assert observation == observation_snapshot


def test_moves_do_not_reach_the_observations_shared_farm_lists():
    # The parser shares farm["farmer"] with the observation dict.
    observation = _observation()
    state = parse(observation)
    farm = observation["farms"][observation["player"]]

    result = Simulator().play_turn(state, Turn(farmer=Action(NORTH)))

    assert result.player.farm.farmer == [4, 3]
    assert farm["farmer"] == [4, 4]
    assert state.player.farm.farmer == [4, 4]


def test_a_full_continuation_evaluation_leaves_the_observation_untouched():
    # Hundreds of simulated turns, all sharing the observation internally.
    observation = _observation()
    state = parse(observation)
    observation_snapshot = copy.deepcopy(observation)

    evaluation = ContinuationEvaluator().evaluate(state)

    assert evaluation.continuation_plans_considered > 10
    assert observation == observation_snapshot
    assert state.raw_observation is observation


def test_failed_simulation_leaves_the_observation_untouched():
    observation = _observation()
    state = parse(observation)
    observation_snapshot = copy.deepcopy(observation)

    with pytest.raises(ValueError):
        Simulator().simulate_plan(state, _plan(_BUY, Turn(farmer=Action("HARVEST"))))

    assert observation == observation_snapshot


# --- results are isolated from the original -----------------------------


@pytest.mark.parametrize("index", range(6))
def test_mutating_a_results_observation_does_not_reach_the_original(index):
    observation = _observation()
    state = parse(observation)
    observation_snapshot = copy.deepcopy(observation)
    name, result = _each_public_call(state)[index]

    result.raw_observation["day"] = 99
    result.raw_observation["private"]["shed"]["WHEAT"] = 50
    result.raw_observation["farms"][0]["farmer"].append(7)

    assert observation == observation_snapshot, name
    assert state.raw_observation == observation_snapshot, name


@pytest.mark.parametrize("index", range(6))
def test_mutating_a_results_state_does_not_reach_the_original(index):
    state = parse(_observation())
    snapshot = copy.deepcopy(state)
    name, result = _each_public_call(state)[index]

    result.player.seeds["WHEAT"] = 99
    result.player.inventory.items["EGG"] = 99
    result.player.farm.farmer.append(0)
    result.market.prices["WHEAT"] = 1
    result.opponent.farm.hands.append([0, 0])

    assert state == snapshot, name


def test_two_results_do_not_share_an_observation():
    state = parse(_observation())
    first = Simulator().play_turn(state, Turn())
    second = Simulator().play_turn(state, Turn())

    first.raw_observation["private"]["seeds"]["WHEAT"] = 42

    assert second.raw_observation["private"]["seeds"]["WHEAT"] == 0


def test_chained_results_do_not_share_an_observation():
    state = parse(_observation())
    first = Simulator().play_turn(state, _BUY)
    second = Simulator().play_turn(first, _PLANT)

    second.raw_observation["day"] = 99

    assert first.raw_observation["day"] == 0


def test_generated_plan_states_do_not_share_the_observation():
    state = parse(_observation())
    (generated,) = WheatPlanGenerator().generate_with_states(state, WHEAT)

    generated.resulting_state.raw_observation["day"] = 99

    assert state.raw_observation["day"] == 0


# --- compatibility -------------------------------------------------------


@pytest.mark.parametrize("index", range(6))
def test_result_observation_is_an_equal_copy_of_the_original(index):
    state = parse(_observation())
    name, result = _each_public_call(state)[index]

    assert result.raw_observation == state.raw_observation, name
    assert result.raw_observation is not state.raw_observation, name


@pytest.mark.parametrize("index", range(6))
def test_results_are_valid_game_states(index):
    state = parse(_observation())
    name, result = _each_public_call(state)[index]

    assert isinstance(result, GameState), name
    validate(result)


def test_parsing_still_keeps_the_observation_itself():
    observation = _observation()

    assert parse(observation).raw_observation is observation
