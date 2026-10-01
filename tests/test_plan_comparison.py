"""Tests for compare_plans and PlanComparison.

A PlanComparison is plain arithmetic, plan A minus plan B, over two
PlanEvaluations from the same decision point. It reports differences in
cash and time side by side and never resolves a tradeoff between them.
"""

import copy
import dataclasses
import json
from pathlib import Path

import pytest

from dimitri.analyst.opportunity import Opportunity, OpportunityKind
from dimitri.executive.decision import Decision
from dimitri.observer.parser import parse
from dimitri.operator.operator import Operator
from dimitri.pipeline import Pipeline
from dimitri.planner.plan import Plan
from dimitri.planner.plan_comparison import PlanComparison, compare_plans
from dimitri.planner.plan_evaluation import PlanEvaluation
from dimitri.planner.plan_evaluator import PlanEvaluator
from dimitri.planner.plan_generator import WheatPlanGenerator
from dimitri.planner.simulator import Simulator
from dimitri.planner.turn import Turn

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"


def _evaluation(*, starting_cash=3000, ending_cash=3000, starting_day=0, ending_day=0, turns=0):
    return PlanEvaluation(
        starting_cash=starting_cash,
        ending_cash=ending_cash,
        cash_delta=ending_cash - starting_cash,
        starting_day=starting_day,
        ending_day=ending_day,
        turns_elapsed=turns,
    )


# --- the model -----------------------------------------------------------


def test_comparison_has_only_factual_difference_fields():
    assert [f.name for f in dataclasses.fields(PlanComparison)] == [
        "ending_cash_difference",
        "cash_delta_difference",
        "turns_elapsed_difference",
        "ending_day_difference",
    ]


def test_comparison_is_immutable():
    comparison = compare_plans(_evaluation(), _evaluation())

    with pytest.raises(dataclasses.FrozenInstanceError):
        comparison.ending_cash_difference = 1


# --- arithmetic ----------------------------------------------------------


def test_equal_plans_have_no_differences():
    evaluation = _evaluation(ending_cash=3044, ending_day=2, turns=52)

    assert compare_plans(evaluation, evaluation) == PlanComparison(0, 0, 0, 0)


def test_higher_ending_cash_is_a_positive_difference():
    comparison = compare_plans(_evaluation(ending_cash=3044), _evaluation(ending_cash=3000))

    assert comparison.ending_cash_difference == 44
    assert comparison.cash_delta_difference == 44


def test_lower_ending_cash_is_a_negative_difference():
    comparison = compare_plans(_evaluation(ending_cash=2990), _evaluation(ending_cash=3044))

    assert comparison.ending_cash_difference == -54
    assert comparison.cash_delta_difference == -54


def test_differences_are_a_minus_b_and_antisymmetric():
    a = _evaluation(ending_cash=3100, ending_day=5, turns=120)
    b = _evaluation(ending_cash=3044, ending_day=2, turns=52)

    forward, backward = compare_plans(a, b), compare_plans(b, a)

    assert forward == PlanComparison(56, 56, 68, 3)
    assert backward == PlanComparison(-56, -56, -68, -3)


def test_turn_and_day_differences():
    comparison = compare_plans(
        _evaluation(ending_day=3, turns=80), _evaluation(ending_day=1, turns=30)
    )

    assert (comparison.turns_elapsed_difference, comparison.ending_day_difference) == (50, 2)


def test_same_day_plans_can_differ_in_turns():
    comparison = compare_plans(
        _evaluation(ending_day=0, turns=20), _evaluation(ending_day=0, turns=3)
    )

    assert (comparison.turns_elapsed_difference, comparison.ending_day_difference) == (17, 0)


# --- tradeoffs are reported, not resolved --------------------------------


def test_plan_that_earns_more_but_takes_longer():
    slow_rich = _evaluation(ending_cash=3200, ending_day=12, turns=270)
    fast_poor = _evaluation(ending_cash=3044, ending_day=2, turns=52)

    comparison = compare_plans(slow_rich, fast_poor)

    assert comparison.ending_cash_difference > 0
    assert comparison.turns_elapsed_difference > 0
    assert comparison.ending_day_difference > 0


def test_plan_that_earns_less_but_finishes_earlier():
    comparison = compare_plans(
        _evaluation(ending_cash=3044, ending_day=2, turns=52),
        _evaluation(ending_cash=3200, ending_day=12, turns=270),
    )

    assert comparison.ending_cash_difference < 0
    assert comparison.turns_elapsed_difference < 0
    assert comparison.ending_day_difference < 0


def test_comparison_exposes_no_judgement():
    names = {f.name for f in dataclasses.fields(PlanComparison)}
    judgements = {"score", "advantage", "utility", "rank", "ranking", "preference", "better", "best", "winner"}

    assert not any(word in name for name in names for word in judgements)
    assert not any(hasattr(PlanComparison, word) for word in judgements)


# --- compatibility -------------------------------------------------------


def test_same_starting_cash_and_day_can_be_compared():
    comparison = compare_plans(
        _evaluation(starting_day=4, ending_day=6, ending_cash=3050),
        _evaluation(starting_day=4, ending_day=4),
    )

    assert comparison.ending_day_difference == 2


def test_different_starting_cash_is_rejected():
    with pytest.raises(ValueError, match="different cash .*3000 vs 2500"):
        compare_plans(_evaluation(starting_cash=3000), _evaluation(starting_cash=2500, ending_cash=2500))


def test_different_starting_days_are_rejected():
    with pytest.raises(ValueError, match="different days .*0 vs 3"):
        compare_plans(_evaluation(starting_day=0), _evaluation(starting_day=3, ending_day=3))


@pytest.mark.parametrize("bad", [None, 3000, {"ending_cash": 3000}, PlanComparison(0, 0, 0, 0)])
def test_non_evaluations_are_rejected(bad):
    with pytest.raises(TypeError, match="must be a PlanEvaluation"):
        compare_plans(bad, _evaluation())
    with pytest.raises(TypeError, match="must be a PlanEvaluation"):
        compare_plans(_evaluation(), bad)


def test_opportunity_kind_is_irrelevant_to_comparison():
    # Evaluations carry no opportunity: any two plans compare the same way.
    assert "opportunity" not in {f.name for f in dataclasses.fields(PlanEvaluation)}


# --- purity --------------------------------------------------------------


def test_comparison_does_not_mutate_either_evaluation():
    a, b = _evaluation(ending_cash=3044, turns=52), _evaluation()
    before = (copy.deepcopy(a), copy.deepcopy(b))

    compare_plans(a, b)

    assert (a, b) == before


def test_comparison_performs_no_simulation_or_evaluation(monkeypatch):
    def _refuse(*args, **kwargs):
        raise AssertionError("comparison must not simulate or evaluate")

    for owner, name in [
        (Simulator, "simulate_plan"),
        (Simulator, "play_turn"),
        (Simulator, "simulate_turn"),
        (PlanEvaluator, "evaluate_plan"),
    ]:
        monkeypatch.setattr(owner, name, _refuse)

    assert compare_plans(_evaluation(ending_cash=3044), _evaluation()).ending_cash_difference == 44


# --- with real evaluations ------------------------------------------------


def _start_state():
    with SAMPLE_OBSERVATION_PATH.open() as f:
        return parse(json.load(f))


def test_comparing_simulated_wheat_and_idle_plans():
    state = _start_state()
    wheat = WheatPlanGenerator().generate(state, Opportunity(OpportunityKind.WHEAT_PRODUCTION))[0]
    hold = Plan(Opportunity(OpportunityKind.HOLD_CASH), turns=(), horizon=0)
    evaluator = PlanEvaluator()

    comparison = compare_plans(evaluator.evaluate_plan(state, wheat), evaluator.evaluate_plan(state, hold))

    # The wheat plan spends 10 on a seed and sells 2 WHEAT at 27 on day 2,
    # dropping and selling in the same turn.
    assert comparison == PlanComparison(
        ending_cash_difference=44,
        cash_delta_difference=44,
        turns_elapsed_difference=51,
        ending_day_difference=2,
    )


def test_real_environment_differences_match_comparison():
    kaggle_environments = pytest.importorskip("kaggle_environments")
    state = _start_state()
    wheat = WheatPlanGenerator().generate(state, Opportunity(OpportunityKind.WHEAT_PRODUCTION))[0]
    operator = Operator()
    received = {}

    def agent(obs):
        received[obs["step"]] = copy.deepcopy(dict(obs))
        step = obs["step"]
        turn = wheat.turns[step] if step < len(wheat.turns) else Turn()
        return operator.execute(Decision(turn=turn))

    env = kaggle_environments.make(
        "kaggriculture",
        configuration={
            "episodeSteps": len(wheat.turns) + 3,
            "weedSpawnChance": 0,
            "townShopUnlockInterval": 10_000,
            "seed": 23,
        },
        debug=True,
    )
    env.run([agent, "pass"])

    start, end = parse(received[0]), parse(received[len(wheat.turns)])
    real_wheat = PlanEvaluation(
        starting_cash=start.player.money,
        ending_cash=end.player.money,
        cash_delta=end.player.money - start.player.money,
        starting_day=start.day,
        ending_day=end.day,
        turns_elapsed=end.step - start.step,
    )
    real_hold = PlanEvaluation(
        starting_cash=start.player.money,
        ending_cash=start.player.money,
        cash_delta=0,
        starting_day=start.day,
        ending_day=start.day,
        turns_elapsed=0,
    )

    comparison = compare_plans(real_wheat, real_hold)

    assert comparison == compare_plans(
        PlanEvaluator().evaluate_plan(start, wheat),
        PlanEvaluator().evaluate_plan(start, Plan(Opportunity(OpportunityKind.HOLD_CASH), (), 0)),
    )
    assert comparison.ending_cash_difference == end.player.money - start.player.money


# --- regression: decisions are unchanged ---------------------------------


def test_pipeline_decision_is_unchanged():
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)

    assert Pipeline().run(observation) == {"farmer": ["PASS"], "hands": [], "market": []}
