"""Tests for the Opportunity and Plan data models.

Opportunity → Plan → Action: an Opportunity describes what could be
pursued, a Plan is a hypothetical sequence of existing Turns pursuing
it, and Action/Turn stay the only executable representation. Nothing
produces or consumes these models yet, so current decisions must be
unchanged.
"""

import dataclasses
import json
from pathlib import Path

import pytest

from dimitri.analyst.analysis import Analysis
from dimitri.analyst.opportunity import Opportunity, OpportunityKind
from dimitri.pipeline import Pipeline
from dimitri.planner.action import (
    BUY_SEED,
    DROP,
    HARVEST,
    NORTH,
    PLANT,
    SELL,
    WATER,
    Action,
)
from dimitri.planner.plan import Plan
from dimitri.planner.turn import Turn

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"

REQUIRED_KINDS = {
    "WHEAT_PRODUCTION",
    "CARROT_PRODUCTION",
    "TOMATO_PRODUCTION",
    "STRAWBERRY_PRODUCTION",
    "MELON_PRODUCTION",
    "ANIMAL_PRODUCTION",
    "MARKET_TRADE",
    "LAND_EXPANSION",
    "HOLD_CASH",
}

TOMATO = Opportunity(OpportunityKind.TOMATO_PRODUCTION)


def _tomato_plan():
    return Plan(
        opportunity=TOMATO,
        turns=(
            Turn(market=(Action(BUY_SEED, "TOMATO", 1),)),
            Turn(farmer=Action(PLANT, "TOMATO")),
            Turn(farmer=Action(WATER)),
            Turn(),
            Turn(farmer=Action(HARVEST)),
            Turn(farmer=Action(DROP)),
            Turn(market=(Action(SELL, "TOMATO", 1),)),
        ),
        horizon=200,
        label="tomato on (4, 4)",
    )


# --- Opportunity ---------------------------------------------------------


def test_every_required_kind_exists():
    assert {kind.name for kind in OpportunityKind} == REQUIRED_KINDS


@pytest.mark.parametrize("kind", list(OpportunityKind))
def test_every_kind_can_be_represented(kind):
    opportunity = Opportunity(kind)

    assert opportunity.kind is kind
    assert OpportunityKind(kind.value) is kind


@pytest.mark.parametrize("name", ["POTATO_PRODUCTION", "wheat_production", ""])
def test_unknown_kind_name_is_rejected(name):
    with pytest.raises(ValueError):
        OpportunityKind(name)


@pytest.mark.parametrize("kind", ["TOMATO_PRODUCTION", None, 3, Action(PLANT, "TOMATO")])
def test_opportunity_rejects_a_kind_that_is_not_an_opportunity_kind(kind):
    with pytest.raises(TypeError, match="OpportunityKind"):
        Opportunity(kind)


def test_opportunity_is_immutable_and_hashable():
    opportunity = Opportunity(OpportunityKind.HOLD_CASH)

    with pytest.raises(dataclasses.FrozenInstanceError):
        opportunity.kind = OpportunityKind.MARKET_TRADE
    assert {opportunity, Opportunity(OpportunityKind.HOLD_CASH)} == {opportunity}


def test_opportunity_is_descriptive_only():
    # No score, probability, evaluation, recommendation, or actions.
    assert {f.name for f in dataclasses.fields(Opportunity)} == {"kind"}


# --- Plan ----------------------------------------------------------------


def test_plan_is_built_from_an_opportunity_and_turns():
    plan = _tomato_plan()

    assert plan.opportunity == TOMATO
    assert len(plan.turns) == 7
    assert all(isinstance(turn, Turn) for turn in plan.turns)


def test_plan_preserves_turn_and_action_order():
    plan = _tomato_plan()

    assert plan.actions() == (
        Action(BUY_SEED, "TOMATO", 1),
        Action(PLANT, "TOMATO"),
        Action(WATER),
        Action(HARVEST),
        Action(DROP),
        Action(SELL, "TOMATO", 1),
    )
    assert plan.turns[3] == Turn()


def test_plan_actions_follow_each_turns_application_order():
    turn = Turn(
        farmer=Action(HARVEST),
        hands=(None, Action(NORTH)),
        market=(Action(SELL, "EGG", 1),),
    )
    plan = Plan(Opportunity(OpportunityKind.MARKET_TRADE), turns=(turn,), horizon=1)

    assert plan.actions() == turn.actions()


def test_plan_turns_list_is_stored_as_tuple():
    turns = [Turn(farmer=Action(WATER)), Turn()]

    plan = Plan(TOMATO, turns=turns, horizon=2)

    assert plan.turns == tuple(turns)
    assert isinstance(plan.turns, tuple)
    turns.append(Turn(farmer=Action(HARVEST)))
    assert len(plan.turns) == 2


def test_plan_is_immutable_and_hashable():
    plan = _tomato_plan()

    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.horizon = 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.turns = ()
    assert hash(plan) == hash(_tomato_plan())
    assert plan == _tomato_plan()


def test_plan_carries_no_score_or_evaluation():
    assert {f.name for f in dataclasses.fields(Plan)} == {
        "opportunity",
        "turns",
        "horizon",
        "label",
    }


# --- horizon -------------------------------------------------------------


def test_horizon_is_the_declared_number_of_game_turns():
    assert _tomato_plan().horizon == 200


def test_horizon_may_equal_the_listed_turns():
    plan = Plan(TOMATO, turns=(Turn(), Turn()), horizon=2)

    assert plan.horizon == len(plan.turns)


def test_horizon_shorter_than_listed_turns_is_rejected():
    with pytest.raises(ValueError, match="must cover"):
        Plan(TOMATO, turns=(Turn(), Turn()), horizon=1)


@pytest.mark.parametrize("horizon", [-1, -10])
def test_negative_horizon_is_rejected(horizon):
    with pytest.raises(ValueError):
        Plan(Opportunity(OpportunityKind.HOLD_CASH), turns=(), horizon=horizon)


@pytest.mark.parametrize("horizon", [1.0, "5", None, True])
def test_non_integer_horizon_is_rejected(horizon):
    with pytest.raises(TypeError, match="horizon"):
        Plan(TOMATO, turns=(), horizon=horizon)


# --- empty plans ---------------------------------------------------------


def test_empty_plan_with_a_horizon_holds_cash():
    plan = Plan(Opportunity(OpportunityKind.HOLD_CASH), turns=(), horizon=24)

    assert plan.turns == ()
    assert plan.actions() == ()
    assert plan.horizon == 24


def test_zero_horizon_empty_plan_is_allowed():
    plan = Plan(Opportunity(OpportunityKind.HOLD_CASH), turns=(), horizon=0)

    assert (plan.turns, plan.horizon, plan.actions()) == ((), 0, ())


def test_label_defaults_to_empty():
    assert Plan(TOMATO, turns=(), horizon=0).label == ""


# --- malformed plans -----------------------------------------------------


@pytest.mark.parametrize("opportunity", [OpportunityKind.TOMATO_PRODUCTION, "TOMATO", None])
def test_plan_requires_an_opportunity(opportunity):
    with pytest.raises(TypeError, match="Plan.opportunity"):
        Plan(opportunity, turns=(), horizon=0)


@pytest.mark.parametrize("turns", [Turn(), "WATER", None])
def test_plan_turns_must_be_a_sequence(turns):
    with pytest.raises(TypeError, match="Plan.turns must be"):
        Plan(TOMATO, turns=turns, horizon=5)


@pytest.mark.parametrize("entry", [Action(WATER), None, ["WATER"]])
def test_plan_turns_must_be_turns_not_bare_actions(entry):
    with pytest.raises(TypeError, match=r"Plan.turns\[1\]"):
        Plan(TOMATO, turns=(Turn(), entry), horizon=5)


def test_plan_label_must_be_a_string():
    with pytest.raises(TypeError, match="label"):
        Plan(TOMATO, turns=(), horizon=0, label=None)


# --- architecture: nothing else changes ----------------------------------


def test_analysis_no_longer_carries_economic_opportunities():
    # EconomicOpportunity was replaced by Opportunity; Analysis keeps its
    # market facts in market_prices and market_inventory.
    names = {f.name for f in dataclasses.fields(Analysis)}

    assert "economic_opportunities" not in names
    assert {"market_prices", "market_inventory"} <= names


def test_pipeline_decision_is_unchanged():
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)

    # Every purchase lowers cash, so the idle turn is still chosen.
    assert Pipeline().run(observation) == {"farmer": ["PASS"], "hands": [], "market": []}
