"""Tests that copy-free chained simulation leaves the continuation search exact.

Profiling showed the continuation search spent nearly all its time deep-
copying GameStates: every simulated turn copied the whole state, often
twice, and its raw observation. Simulation is copy-on-write, so the
Simulator now chains its internal steps without copying and isolates
only the state each public call returns; plan builders chain turns with
``play_turn(..., isolated=False)`` and isolate the one state they hand on.

These tests check that this solves exactly the same problem:

- the benchmark projections are unchanged;
- an exhaustive reference search that isolates every simulated turn,
  as the Simulator did before, gives the same cash and plans from a broad
  set of states;
- chaining without isolation never mutates a state, and isolated results
  share nothing mutable;
- projections still match the real environment.
"""

import copy
import json
from pathlib import Path

import pytest

from dimitri.analyst.opportunity import Opportunity, OpportunityKind
from dimitri.executive.decision import Decision
from dimitri.observer.parser import parse
from dimitri.operator.operator import Operator
from dimitri.planner.continuation import ContinuationEvaluator
from dimitri.planner.plan_generator import TomatoPlanGenerator, WheatPlanGenerator
from dimitri.planner.simulator import Simulator, _working_copy
from dimitri.planner.turn import Turn
from dimitri.utils.constants import LAST_ACTION_STEP

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"
SPAWN = (4, 4)
WHEAT = Opportunity(OpportunityKind.WHEAT_PRODUCTION)
TOMATO = Opportunity(OpportunityKind.TOMATO_PRODUCTION)


def _plant(crop, planted_day, *, watered=False, unwatered=0, yield_units=0, final=False):
    if crop == "WHEAT":
        lifespan = (planted_day + 5) * 24
    else:
        lifespan = (planted_day + 12) * 24 if final else -1
    return {
        "kind": "PLANT",
        "crop": crop,
        "planted_day": planted_day,
        "watered_today": watered,
        "consecutive_unwatered": unwatered,
        "yield_units": yield_units,
        "max_lifespan_step": lifespan,
        "fertilized_until_day": -1,
    }


def _state(*, step=0, money=None, farmer=SPAWN, tiles=None, seeds=None, carried=None, shed=None):
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)
    observation["step"] = step
    observation["day"], observation["hour"] = divmod(step, 24)
    farm = observation["farms"][observation["player"]]
    if money is not None:
        farm["money"] = money
    farm["farmer"] = list(farmer)
    for (x, y), tile in (tiles or {}).items():
        farm["tiles"][y][x] = copy.deepcopy(tile)
    private = observation["private"]
    private["seeds"].update(seeds or {})
    private["shed"].update(shed or {})
    if carried is not None:
        private["inventories"] = [dict(carried)]
    return parse(observation)


def _sequence(evaluation):
    """The winning plans' opportunity kinds, run-length encoded."""
    runs = []
    for plan in evaluation.plans:
        kind = plan.opportunity.kind.name.removesuffix("_PRODUCTION")
        if runs and runs[-1][0] == kind:
            runs[-1][1] += 1
        else:
            runs.append([kind, 1])
    return [(kind, n) for kind, n in runs]


# --- the benchmark is unchanged -----------------------------------------


@pytest.mark.parametrize(
    ("day", "cash", "sequence", "considered"),
    [
        (0, 8005, [("WHEAT", 2), ("TOMATO", 1)], 32),
        (5, 7618, [("TOMATO", 1)], 24),
        (10, 5507, [("WHEAT", 3), ("TOMATO", 1)], 21),
        (15, 5246, [("WHEAT", 1), ("TOMATO", 1)], 11),
        (20, 3649, [("TOMATO", 1)], 5),
        (24, 3100, [("WHEAT", 2)], 2),
        (27, 3048, [("WHEAT", 1)], 1),
        (28, 3000, [], 0),
    ],
)
def test_benchmark_projection(day, cash, sequence, considered):
    evaluation = ContinuationEvaluator().evaluate(_state(step=24 * day))

    assert evaluation.projected_terminal_cash == cash
    assert _sequence(evaluation) == sequence
    assert evaluation.continuation_plans_considered == considered


# --- an exhaustive reference --------------------------------------------


class _IsolatingSimulator(Simulator):
    """The Simulator as it was before: every simulated step works on, and returns, a copy."""

    def _play_turn(self, game_state, turn):
        return super()._play_turn(_working_copy(game_state), turn)

    def play_turn(self, game_state, turn, *, isolated=True):
        return super().play_turn(game_state, turn, isolated=True)


def _reference(state, simulator):
    """Exhaustive continuation search, written out independently of ContinuationEvaluator.

    It replays every generated plan with ``simulate_plan`` instead of
    reusing the generator's state, and explores every branch. HOLD_CASH
    comes first and an earlier branch wins a tie, as documented.
    Returns ``(terminal cash, plans)``.
    """
    best = (state.player.money, ())
    if state.step > LAST_ACTION_STEP:
        return best
    generators = (WheatPlanGenerator(simulator), TomatoPlanGenerator(simulator))
    for generator in generators:
        for plan in generator.generate(state, Opportunity(generator.opportunity_kind)):
            if not plan.turns or state.step + len(plan.turns) - 1 > LAST_ACTION_STEP:
                continue
            following = simulator.simulate_plan(state, plan)
            if following.step <= state.step:
                continue
            cash, plans = _reference(following, simulator)
            if cash > best[0]:
                best = (cash, (plan, *plans))
    return best


REFERENCE_STATES = {
    "hold wins: too late": {"step": 24 * 28},
    "hold wins: nothing affordable": {"step": 24 * 20, "money": 5},
    "nothing viable: last action": {"step": LAST_ACTION_STEP},
    "wheat wins from day 18": {"step": 24 * 18},
    "wheat wins from day 22": {"step": 24 * 22 + 7},
    "existing wheat": {"step": 24 * 17 + 5, "tiles": {SPAWN: _plant("WHEAT", 17, unwatered=1, yield_units=1)}},
    "existing tomato holding yield": {
        "step": 24 * 11, "tiles": {SPAWN: _plant("TOMATO", 0, yield_units=4, final=True)},
    },
    "existing tomato mid-life": {"step": 24 * 15 + 3, "tiles": {SPAWN: _plant("TOMATO", 7, yield_units=1)}},
    "late partial tomato": {"step": 24 * 26 + 2, "tiles": {(4, 3): _plant("TOMATO", 19, watered=True, yield_units=1)}},
    "carried wheat and tomato": {"step": 24 * 21 + 4, "farmer": (2, 2), "carried": {"WHEAT": 3, "TOMATO": 2}},
    "shed wheat and tomato": {"step": 24 * 23, "shed": {"WHEAT": 4, "TOMATO": 5}},
    "held seeds": {"step": 24 * 19 + 20, "seeds": {"WHEAT": 1, "TOMATO": 1}},
}


@pytest.mark.parametrize("name", list(REFERENCE_STATES))
def test_projection_matches_the_exhaustive_reference(name):
    state = _state(**REFERENCE_STATES[name])

    evaluation = ContinuationEvaluator().evaluate(state)
    cash, plans = _reference(state, _IsolatingSimulator())

    assert (evaluation.projected_terminal_cash, evaluation.plans) == (cash, plans)


def test_reference_states_cover_every_kind_of_winner():
    winners = set()
    for kwargs in REFERENCE_STATES.values():
        plans = ContinuationEvaluator().evaluate(_state(**kwargs)).plans
        winners.add(plans[0].opportunity.kind if plans else OpportunityKind.HOLD_CASH)

    assert winners == {
        OpportunityKind.HOLD_CASH,
        OpportunityKind.WHEAT_PRODUCTION,
        OpportunityKind.TOMATO_PRODUCTION,
    }


def test_generators_build_the_same_plans_and_states_as_with_per_turn_copies():
    for kwargs in REFERENCE_STATES.values():
        state = _state(**kwargs)
        for kind, cls in ((WHEAT, WheatPlanGenerator), (TOMATO, TomatoPlanGenerator)):
            assert cls().generate_with_states(state, kind) == cls(_IsolatingSimulator()).generate_with_states(state, kind)


def test_ties_still_keep_the_earlier_branch():
    # Two generators offering the same plan tie: the earlier one is kept.
    state = _state(step=24 * 27)
    wheat = WheatPlanGenerator()

    evaluation = ContinuationEvaluator(generators=[wheat, WheatPlanGenerator()]).evaluate(state)
    (plan,) = evaluation.plans

    assert evaluation.continuation_plans_considered == 2
    assert plan == wheat.generate(state, WHEAT)[0]


# --- the copy-on-write contract -----------------------------------------


def _chain(state, plan, *, isolated):
    simulator = Simulator()
    for turn in plan.turns:
        state = simulator.play_turn(state, turn, isolated=isolated)
    return state


@pytest.mark.parametrize("generator", [WheatPlanGenerator(), TomatoPlanGenerator()], ids=["wheat", "tomato"])
def test_chaining_without_isolation_never_mutates_any_state(generator):
    state = _state(farmer=(1, 2))
    snapshot = copy.deepcopy(state)
    plan = generator.generate(state, Opportunity(generator.opportunity_kind))[0]

    simulator = Simulator()
    chained, states = state, [state]
    for turn in plan.turns:
        chained = simulator.play_turn(chained, turn, isolated=False)
        states.append(chained)
    snapshots = copy.deepcopy(states)
    _chain(chained, plan.__class__(plan.opportunity, (), 0), isolated=False)

    assert state == snapshot
    assert states == snapshots
    assert chained == _chain(state, plan, isolated=True)


def test_isolate_returns_an_equal_state_that_shares_nothing_mutable():
    state = Simulator().play_turn(_state(), Turn(), isolated=False)

    isolated = Simulator().isolate(state)
    isolated.player.seeds["WHEAT"] = 99
    isolated.player.inventory.items["EGG"] = 99
    isolated.player.farm.farmer.append(0)
    isolated.market.prices["WHEAT"] = 1
    isolated.raw_observation["day"] = 99

    assert isolated is not state
    assert state == Simulator().play_turn(_state(), Turn())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"step": 266, "shed": {"TOMATO": 4}},
        {"step": 51, "shed": {"WHEAT": 2}},
        {},
    ],
    ids=["tomato sale", "wheat sale", "fresh"],
)
def test_generated_states_share_nothing_mutable_with_the_input(kwargs):
    # A sale leaves the seeds untouched; they must still not be shared.
    state = _state(**kwargs)
    snapshot = copy.deepcopy(state)
    generated = [
        g
        for cls, kind in ((WheatPlanGenerator, WHEAT), (TomatoPlanGenerator, TOMATO))
        for g in cls().generate_with_states(state, kind)
    ]
    assert generated

    for g in generated:
        result = g.resulting_state
        result.player.seeds["WHEAT"] = 99
        result.player.farm.farmer.append(0)
        result.player.farm.unlocked_quadrants.append("SE")
        result.opponent.farm.hands.append([0, 0])
        result.market.inventory["WHEAT"] = 1
        result.raw_observation["day"] = 99

    assert state == snapshot


class _CountingSimulator(Simulator):
    def __init__(self):
        self.isolated_turns = 0
        self.chained_turns = 0
        self.isolations = 0

    def play_turn(self, game_state, turn, *, isolated=True):
        if isolated:
            self.isolated_turns += 1
        else:
            self.chained_turns += 1
        return super().play_turn(game_state, turn, isolated=isolated)

    def isolate(self, game_state):
        self.isolations += 1
        return super().isolate(game_state)

    def simulate_plan(self, game_state, plan):
        raise AssertionError("the generated plan must not be replayed")


@pytest.mark.parametrize("cls, kind", [(WheatPlanGenerator, WHEAT), (TomatoPlanGenerator, TOMATO)])
def test_a_generated_plan_is_chained_and_isolated_once(cls, kind):
    simulator = _CountingSimulator()

    (generated,) = cls(simulator).generate_with_states(_state(), kind)

    # Larger tomato programs that are rejected are simulated too, but only
    # the accepted one is isolated, once, and nothing is replayed.
    assert simulator.chained_turns >= len(generated.plan.turns)
    assert simulator.isolated_turns == 0
    assert simulator.isolations == 1


def test_evaluation_never_replays_generated_plans():
    simulator = _CountingSimulator()

    evaluation = ContinuationEvaluator(
        simulator=simulator,
        generators=[WheatPlanGenerator(simulator), TomatoPlanGenerator(simulator)],
    ).evaluate(_state(step=24 * 15))

    assert simulator.isolations == evaluation.continuation_plans_considered


def test_projected_plans_stay_within_the_season():
    state = _state()
    for plan in ContinuationEvaluator().evaluate(state).plans:
        state = Simulator().simulate_plan(state, plan)
        assert state.step - 1 <= LAST_ACTION_STEP


# --- the real environment -----------------------------------------------


def _play_season_after(prefix_of):
    """Play a prefix, project from the live observation, then play the projected plans to the end.

    ``prefix_of(observation)`` returns the prefix's turns from the game's
    first parsed observation. Returns the state projected from, the
    projection, and the season's final bank money (the reward).
    """
    kaggle_environments = pytest.importorskip("kaggle_environments")
    operator = Operator()
    run = {}

    def agent(obs):
        step = obs["step"]
        if step == 0:
            run["prefix"] = prefix_of(parse(copy.deepcopy(dict(obs))))
        prefix = run["prefix"]
        if step < len(prefix):
            return operator.execute(Decision(turn=prefix[step]))
        if step == len(prefix):
            run["start"] = parse(copy.deepcopy(dict(obs)))
            run["projection"] = ContinuationEvaluator().evaluate(run["start"])
            turns = [t for plan in run["projection"].plans for t in plan.turns]
            run["schedule"] = {step + i: t for i, t in enumerate(turns)}
        return operator.execute(Decision(turn=run["schedule"].get(step, Turn())))

    env = kaggle_environments.make(
        "kaggriculture",
        configuration={"weedSpawnChance": 0, "townShopUnlockInterval": 10_000, "seed": 31},
        debug=True,
    )
    env.run([agent, "pass"])
    return run["start"], run["projection"], env.steps[-1][0].reward


def _plan_prefix(cls, kind, length):
    return lambda state: list(cls().generate(state, kind)[0].turns[:length])


def test_real_environment_projection_from_an_existing_wheat():
    start, projection, final_money = _play_season_after(_plan_prefix(WheatPlanGenerator, WHEAT, 30))

    assert start.player.farm.tiles[4][4].crop == "WHEAT"
    assert projection.plans[0].label == "continue WHEAT at (4, 4)"
    assert projection.projected_terminal_cash == final_money


def test_real_environment_projection_from_an_existing_tomato():
    start, projection, final_money = _play_season_after(_plan_prefix(TomatoPlanGenerator, TOMATO, 24 * 9 + 5))

    assert start.player.farm.tiles[4][4].crop == "TOMATO"
    assert start.player.farm.tiles[4][4].yield_units > 0
    # Whichever plans win, the shared scheduler keeps the wave alive and
    # harvests and sells it along the way.
    sold = [a for plan in projection.plans for a in plan.actions() if a.action_type == "SELL" and a.target == "TOMATO"]
    assert sold
    assert projection.projected_terminal_cash == final_money


def test_real_environment_projection_late_in_the_season():
    start, projection, final_money = _play_season_after(lambda state: [Turn()] * (24 * 20))

    assert start.day == 20
    assert projection.plans
    assert projection.projected_terminal_cash == final_money
