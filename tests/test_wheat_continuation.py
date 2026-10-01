"""Tests for WheatPlanGenerator continuing an investment from an intermediate state.

Dimitri observes and replans every turn, so the wheat generator must
work during a wheat investment, not only before one. From the current
GameState it continues a living wheat plant first, then sells wheat the
farmer carries or the shed holds, and only otherwise starts new wheat,
using a held seed before buying one.

Replanning tests interrupt a fresh wheat plan after N turns, generate
again from the state reached, and check that the continuation completes
the same investment: the season reaches the same final state, with no
second seed bought and no second wheat planted.

Real-environment tests do the same in the installed Kaggriculture
environment through the Operator, with random weeds and town-shop
unlocks switched off and a passing opponent, and compare the
continuation's projected state with the real one.
"""

import copy
import json
from pathlib import Path

import pytest

from dimitri.analyst.opportunity import Opportunity, OpportunityKind
from dimitri.executive.decision import Decision
from dimitri.observer.parser import parse
from dimitri.operator.operator import Operator
from dimitri.planner.action import (
    BUY_SEED,
    DROP,
    EAST,
    HARVEST,
    NORTH,
    PLANT,
    SELL,
    SOUTH,
    WATER,
    WEST,
    Action,
)
from dimitri.planner.continuation import ContinuationEvaluator
from dimitri.planner.plan import Plan
from dimitri.planner.plan_generator import WheatPlanGenerator, living_wheat
from dimitri.planner.simulator import Simulator
from dimitri.planner.turn import Turn

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"
SPAWN = (4, 4)
WHEAT = Opportunity(OpportunityKind.WHEAT_PRODUCTION)
WEED = {"kind": "WEED"}


def _wheat(planted_day, *, watered=False, unwatered=0, yield_units=1, crop="WHEAT"):
    """A raw plant tile as the environment writes it."""
    return {
        "kind": "PLANT",
        "crop": crop,
        "planted_day": planted_day,
        "watered_today": watered,
        "consecutive_unwatered": unwatered,
        "yield_units": yield_units,
        "max_lifespan_step": (planted_day + 5) * 24 if crop == "WHEAT" else -1,
        "fertilized_until_day": -1,
    }


def _state(*, step=0, farmer=SPAWN, tiles=None, seeds=None, carried=None, shed=None):
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)
    observation["step"] = step
    observation["day"], observation["hour"] = divmod(step, 24)
    farm = observation["farms"][observation["player"]]
    farm["farmer"] = list(farmer)
    for (x, y), tile in (tiles or {}).items():
        farm["tiles"][y][x] = copy.deepcopy(tile)
    private = observation["private"]
    private["seeds"].update(seeds or {})
    private["shed"].update(shed or {})
    if carried is not None:
        private["inventories"] = [dict(carried)]
    return parse(observation)


def _generated(state):
    (generated,) = WheatPlanGenerator().generate_with_states(state, WHEAT)
    return generated


def _plan(state):
    return _generated(state).plan


def _actions(plan):
    return list(plan.actions())


def _types(plan):
    return [a.action_type for a in plan.actions()]


def _steps_of(plan, action_type, start_step=0):
    return [
        start_step + i
        for i, turn in enumerate(plan.turns)
        if any(a.action_type == action_type for a in turn.actions())
    ]


def _final(state, plan):
    return Simulator().simulate_plan(state, plan)


def _prefix(state, plan, n):
    return Simulator().simulate_plan(state, Plan(WHEAT, turns=plan.turns[:n], horizon=n))


# --- what counts as living wheat ----------------------------------------


def test_living_wheat_is_a_wheat_plant_tile():
    state = _state(tiles={(1, 1): _wheat(0), (2, 2): WEED, (3, 3): _wheat(0, crop="TOMATO")})

    assert living_wheat(state) == [(1, 1)]


def test_living_wheat_is_ordered_oldest_first_then_by_row_and_column():
    state = _state(
        step=48,
        tiles={(0, 3): _wheat(1), (3, 1): _wheat(0), (1, 1): _wheat(0), (4, 0): _wheat(2)},
    )

    assert living_wheat(state) == [(1, 1), (3, 1), (0, 3), (4, 0)]


def test_weed_is_not_continued():
    plan = _plan(_state(tiles={SPAWN: WEED}))

    assert plan.label == "WHEAT at (4, 3)"
    assert plan.turns[0].market == (Action(BUY_SEED, "WHEAT", 1),)


def test_empty_state_still_starts_fresh_wheat():
    plan = _plan(_state())

    assert plan.label == "WHEAT at (4, 4)"
    assert _types(plan) == [BUY_SEED, PLANT, WATER, WATER, WATER, HARVEST, DROP, SELL]


# --- a held seed --------------------------------------------------------


def test_held_seed_is_planted_without_buying_another():
    state = _state(seeds={"WHEAT": 1})

    plan = _plan(state)
    final = _final(state, plan)

    assert plan.label == "WHEAT at (4, 4)"
    assert _types(plan) == [PLANT, WATER, WATER, WATER, HARVEST, DROP, SELL]
    assert final.player.seeds["WHEAT"] == 0
    assert final.player.money > state.player.money


def test_only_one_of_several_held_seeds_is_used():
    state = _state(seeds={"WHEAT": 3})

    final = _final(state, _plan(state))

    assert final.player.seeds["WHEAT"] == 2


# --- a living plant -----------------------------------------------------


def test_newly_planted_unwatered_wheat_is_watered_first():
    state = _state(step=5, tiles={SPAWN: _wheat(0, unwatered=1)})

    plan = _plan(state)

    assert plan.label == "continue WHEAT at (4, 4)"
    assert plan.turns[0] == Turn(farmer=Action(WATER))
    assert BUY_SEED not in _types(plan) and PLANT not in _types(plan)


def test_wheat_watered_today_is_not_watered_again():
    state = _state(step=5, tiles={SPAWN: _wheat(0, watered=True, unwatered=1)})

    plan = _plan(state)

    assert plan.turns[0] == Turn()
    assert _steps_of(plan, WATER, start_step=5) == [24, 48]


def test_growing_wheat_is_preserved_until_harvest_and_sold():
    state = _state(step=24 + 7, tiles={SPAWN: _wheat(0)})

    plan = _plan(state)
    final = _final(state, plan)

    assert _types(plan) == [WATER, WATER, HARVEST, DROP, SELL]
    assert _steps_of(plan, HARVEST, start_step=31) == [49]
    assert final.player.farm.tiles[4][4] is None
    assert final.player.money > state.player.money


def test_harvestable_watered_wheat_is_harvested_at_once():
    state = _state(step=48 + 3, tiles={SPAWN: _wheat(0, watered=True, yield_units=2)})

    plan = _plan(state)

    assert _actions(plan) == [Action(HARVEST), Action(DROP), Action(SELL, "WHEAT", 2)]


def test_harvestable_wheat_is_watered_first_when_water_adds_yield():
    # Age 3 is inside wheat's watering window (ages 2 to 4).
    state = _state(step=72 + 3, tiles={SPAWN: _wheat(0, yield_units=2)})

    plan = _plan(state)

    assert _actions(plan) == [
        Action(WATER), Action(HARVEST), Action(DROP), Action(SELL, "WHEAT", 3),
    ]


def test_decaying_wheat_is_harvested_without_watering():
    # Age 5: decay began at step 120, and water no longer adds yield.
    state = _state(step=121, tiles={SPAWN: _wheat(0, yield_units=3)})

    plan = _plan(state)

    assert _actions(plan) == [Action(HARVEST), Action(DROP), Action(SELL, "WHEAT", 3)]


def test_wheat_that_cannot_be_saved_is_not_continued():
    # Planted today and still unwatered at hour 23, out of the farmer's
    # reach: it becomes a weed tonight, so new wheat is started instead.
    state = _state(step=23, tiles={(0, 0): _wheat(0, unwatered=1)})

    plan = _plan(state)

    assert plan.label == "WHEAT at (4, 4)"


# --- liquidation --------------------------------------------------------


def test_carried_wheat_is_dropped_and_sold():
    state = _state(step=50, farmer=(4, 3), carried={"WHEAT": 2})

    plan = _plan(state)
    final = _final(state, plan)

    assert plan.label == "sell WHEAT"
    assert _actions(plan) == [Action(SOUTH), Action(DROP), Action(SELL, "WHEAT", 2)]
    assert final.player.inventory.items["WHEAT"] == 0
    assert final.player.money > state.player.money


def test_shed_wheat_is_sold():
    state = _state(step=51, shed={"WHEAT": 5})

    plan = _plan(state)

    assert plan.label == "sell WHEAT"
    assert plan.turns == (Turn(market=(Action(SELL, "WHEAT", 5),)),)


def test_carried_and_shed_wheat_are_sold_together():
    state = _state(step=50, carried={"WHEAT": 2}, shed={"WHEAT": 3})

    assert _actions(_plan(state)) == [Action(DROP), Action(SELL, "WHEAT", 5)]


def test_carried_wheat_dropped_by_the_night_is_not_dropped_again():
    # Walking from (0, 0) at hour 23, the night returns the farmer to the
    # spawn tile and drops its inventory into the shed.
    state = _state(step=23, farmer=(0, 0), carried={"WHEAT": 2})

    plan = _plan(state)

    assert _actions(plan) == [Action(EAST), Action(SELL, "WHEAT", 2)]


def test_living_wheat_plan_also_sells_wheat_already_held():
    state = _state(step=48 + 3, tiles={SPAWN: _wheat(0, watered=True, yield_units=2)}, shed={"WHEAT": 4})

    assert _actions(_plan(state))[-1] == Action(SELL, "WHEAT", 6)


def test_living_wheat_is_continued_before_held_wheat_is_sold_alone():
    state = _state(step=5, tiles={SPAWN: _wheat(0, unwatered=1)}, shed={"WHEAT": 4})

    assert _plan(state).label == "continue WHEAT at (4, 4)"


def test_other_goods_are_not_sold():
    state = _state(step=51, shed={"EGG": 5})

    plan = _plan(state)

    assert plan.label == "WHEAT at (4, 4)"
    assert _final(state, plan).player.inventory.items["EGG"] == 5


# --- movement -----------------------------------------------------------


def test_continuation_starts_from_the_farmers_current_position():
    state = _state(step=48 + 3, farmer=(0, 0), tiles={(2, 3): _wheat(0, watered=True, yield_units=2)})

    plan = _plan(state)

    assert plan.label == "continue WHEAT at (2, 3)"
    assert _actions(plan) == [
        Action(EAST), Action(EAST), Action(SOUTH), Action(SOUTH), Action(SOUTH),
        Action(HARVEST),
        Action(EAST), Action(EAST), Action(SOUTH),
        Action(DROP), Action(SELL, "WHEAT", 2),
    ]


def test_continuation_walks_back_to_the_plant_each_day():
    state = _state(step=10, farmer=(0, 0), tiles={(4, 3): _wheat(0, watered=True)})

    plan = _plan(state)
    final = _final(state, plan)

    # Day 1 and day 2 start at spawn, one step south of the plant.
    assert _steps_of(plan, NORTH, start_step=10)[-2:] == [24, 48]
    assert final.player.farm.tiles[3][4] is None


# --- several living wheat plants ----------------------------------------


def test_oldest_living_wheat_is_continued_even_when_farther():
    state = _state(step=24 + 2, tiles={SPAWN: _wheat(1, watered=True), (0, 0): _wheat(0, watered=True)})

    assert _plan(state).label == "continue WHEAT at (0, 0)"


def test_same_age_wheat_is_chosen_by_row_then_column():
    state = _state(step=2, tiles={(3, 4): _wheat(0, watered=True), (4, 3): _wheat(0, watered=True)})

    assert _plan(state).label == "continue WHEAT at (4, 3)"


def test_wheat_that_cannot_be_saved_gives_way_to_the_next_living_wheat():
    state = _state(step=23, tiles={(0, 0): _wheat(0, unwatered=1), (4, 3): _wheat(0, watered=True)})

    assert _plan(state).label == "continue WHEAT at (4, 3)"


def test_several_living_wheat_plants_give_exactly_one_plan():
    tiles = {(x, 0): _wheat(0, watered=True) for x in range(5)}

    plans = WheatPlanGenerator().generate(_state(step=2, tiles=tiles), WHEAT)

    assert len(plans) == 1
    assert plans[0].label == "continue WHEAT at (0, 0)"


# --- replanning ---------------------------------------------------------


def _replanning_scenario(tiles):
    start = _state(tiles=tiles)
    plan = _plan(start)
    return start, plan, _final(start, plan)


def _assert_continuation_completes_the_investment(start, plan, full_final, n):
    interrupted = _prefix(start, plan, n)
    generated = _generated(interrupted)
    continuation = generated.plan
    final = generated.resulting_state

    assert (final.step, final.player, final.market) == (full_final.step, full_final.player, full_final.market)
    prefix_types = [a.action_type for turn in plan.turns[:n] for a in turn.actions()]
    combined = prefix_types + _types(continuation)
    assert combined.count(BUY_SEED) == 1
    assert combined.count(PLANT) == 1
    return continuation


@pytest.mark.parametrize("tiles", [{}, {SPAWN: WEED}], ids=["plot at spawn", "plot away from spawn"])
@pytest.mark.parametrize(
    "point", ["after BUY_SEED", "after PLANT", "after WATER", "during growth", "at harvest", "after HARVEST"]
)
def test_replanning_at_a_lifecycle_point_completes_the_same_investment(tiles, point):
    start, plan, full_final = _replanning_scenario(tiles)
    n = {
        "after BUY_SEED": _steps_of(plan, BUY_SEED)[0] + 1,
        "after PLANT": _steps_of(plan, PLANT)[0] + 1,
        "after WATER": _steps_of(plan, WATER)[0] + 1,
        "during growth": 30,
        "at harvest": _steps_of(plan, HARVEST)[0],
        "after HARVEST": _steps_of(plan, HARVEST)[0] + 1,
    }[point]

    continuation = _assert_continuation_completes_the_investment(start, plan, full_final, n)

    expected_label = {
        "after BUY_SEED": plan.label,
        "after HARVEST": "sell WHEAT",
    }.get(point, "continue " + plan.label)
    assert continuation.label == expected_label


@pytest.mark.parametrize("tiles", [{}, {SPAWN: WEED}], ids=["plot at spawn", "plot away from spawn"])
def test_replanning_after_any_turn_completes_the_same_investment(tiles):
    start, plan, full_final = _replanning_scenario(tiles)

    for n in range(len(plan.turns)):
        _assert_continuation_completes_the_investment(start, plan, full_final, n)


def _drop_without_sale(plan):
    """The plan up to its harvest, then a lone DROP: the shed holds the wheat, unsold."""
    harvest = _steps_of(plan, HARVEST)[0]
    return harvest + 1, list(plan.turns[: harvest + 1]) + [Turn(farmer=Action(DROP))]


@pytest.mark.parametrize("tiles", [{}, {SPAWN: WEED}], ids=["plot at spawn", "plot away from spawn"])
def test_replanning_after_a_drop_without_its_sale_sells_the_wheat(tiles):
    # Generated plans drop and sell in one turn, but an observed state may
    # hold dropped, unsold wheat: replanning sells it at once.
    start, plan, full_final = _replanning_scenario(tiles)
    _, prefix = _drop_without_sale(plan)
    if tiles:
        prefix[-1:-1] = [Turn(farmer=Action(SOUTH))]  # back to the shed first
    dropped = Simulator().simulate_plan(start, Plan(WHEAT, turns=tuple(prefix), horizon=len(prefix)))
    held = dropped.player.inventory.items["WHEAT"]

    generated = _generated(dropped)

    assert held > 0
    assert generated.plan.label == "sell WHEAT"
    assert generated.plan.turns == (Turn(market=(Action(SELL, "WHEAT", held),)),)
    assert generated.resulting_state.player.inventory.items["WHEAT"] == 0


def test_nothing_is_left_to_continue_after_the_sale():
    start, plan, _ = _replanning_scenario({})
    after_sale = _final(start, plan)

    # The investment is finished, so the generator starts new wheat.
    assert _plan(after_sale).label == "WHEAT at (4, 4)"


# --- the season's end ---------------------------------------------------


def test_harvest_is_continued_when_the_sale_fits_by_the_last_action():
    state = _state(step=716, tiles={SPAWN: _wheat(27, watered=True, yield_units=2)})

    plan = _plan(state)

    # The drop is applied before the market, so the sale shares its turn.
    assert _steps_of(plan, SELL, start_step=716) == [717]


def test_harvest_on_the_second_last_action_still_sells_in_the_drop_turn():
    state = _state(step=717, tiles={SPAWN: _wheat(27, watered=True, yield_units=2)})

    plan = _plan(state)

    assert _actions(plan) == [Action(HARVEST), Action(DROP), Action(SELL, "WHEAT", 2)]
    assert _steps_of(plan, SELL, start_step=717) == [718]


def test_no_continuation_when_the_sale_would_miss_the_last_action():
    state = _state(step=718, tiles={SPAWN: _wheat(27, watered=True, yield_units=2)})

    assert WheatPlanGenerator().generate(state, WHEAT) == ()


def test_unsellable_wheat_is_not_counted_as_terminal_cash():
    state = _state(step=718, tiles={SPAWN: _wheat(27, watered=True, yield_units=2)})

    evaluation = ContinuationEvaluator().evaluate(state)

    assert evaluation.projected_terminal_cash == state.player.money
    assert evaluation.plans == ()


def test_sellable_carried_wheat_is_sold_when_the_plant_is_too_late():
    # The plant's harvest cannot be sold by step 718, but the carried
    # wheat can: only the carried wheat reaches the bank.
    state = _state(step=718, tiles={SPAWN: _wheat(27, watered=True, yield_units=2)}, carried={"WHEAT": 3})

    evaluation = ContinuationEvaluator().evaluate(state)
    (plan,) = evaluation.plans

    assert plan.label == "sell WHEAT"
    assert _actions(plan) == [Action(DROP), Action(SELL, "WHEAT", 3)]
    assert evaluation.projected_terminal_cash == _final(state, plan).player.money


def test_shed_wheat_can_be_sold_on_the_last_action_step():
    state = _state(step=718, shed={"WHEAT": 2})

    plan = _plan(state)

    assert plan.turns == (Turn(market=(Action(SELL, "WHEAT", 2),)),)


# --- continuation evaluation and state reuse ----------------------------


def test_continuation_evaluation_keeps_the_existing_wheat():
    # Whichever hypothesis wins first, the shared scheduler keeps the wheat
    # alive and harvests and sells it in that plan.
    state = _state(step=5, tiles={SPAWN: _wheat(0, unwatered=1)})

    evaluation = ContinuationEvaluator().evaluate(state)
    first = evaluation.plans[0]

    assert any(a.action_type == SELL and a.target == "WHEAT" for a in first.actions())
    assert _final(state, first).player.farm.tiles[4][4] is None  # harvested, not a weed
    assert evaluation.projected_terminal_cash > state.player.money


def test_continuation_evaluation_sells_held_wheat():
    state = _state(step=24 * 28, shed={"WHEAT": 4})

    evaluation = ContinuationEvaluator().evaluate(state)

    assert evaluation.plans[0].label == "sell WHEAT"
    assert evaluation.projected_terminal_cash > state.player.money


@pytest.mark.parametrize(
    "kwargs",
    [
        {"seeds": {"WHEAT": 1}},
        {"step": 5, "tiles": {SPAWN: _wheat(0, unwatered=1)}},
        {"step": 50, "farmer": (4, 3), "carried": {"WHEAT": 2}},
        {"step": 51, "shed": {"WHEAT": 5}},
    ],
    ids=["held seed", "living wheat", "carried wheat", "shed wheat"],
)
def test_generated_state_is_reused_not_replayed(kwargs, monkeypatch):
    state = _state(**kwargs)
    expected = _final(state, _plan(state))

    def _refuse(*args, **kwargs):
        raise AssertionError("generation must not replay the finished plan")

    monkeypatch.setattr(Simulator, "simulate_plan", _refuse)
    generated = _generated(state)

    assert generated.resulting_state == expected


def test_continuation_generation_does_not_mutate_the_state():
    state = _state(step=50, farmer=(0, 0), tiles={(4, 3): _wheat(0, watered=True)}, carried={"WHEAT": 1})
    before = copy.deepcopy(state)

    _generated(state)

    assert state == before


# --- the real environment -----------------------------------------------


def _play_interrupted(prefix_of):
    """Play part of a fresh wheat plan, replan from the live observation, and play the continuation.

    ``prefix_of(plan)`` returns the turns played before replanning, given
    the full plan generated from the game's first observation.
    """
    kaggle_environments = pytest.importorskip("kaggle_environments")
    received, run = {}, {}
    operator = Operator()

    def agent(obs):
        step = obs["step"]
        received[step] = copy.deepcopy(dict(obs))
        if step == 0:
            run["full"] = _generated(parse(received[0]))
            run["prefix"] = prefix_of(run["full"].plan)
        prefix = run["prefix"]
        if step < len(prefix):
            return operator.execute(Decision(turn=prefix[step]))
        if step == len(prefix):
            run["continuation"] = _generated(parse(received[step]))
        turns = run["continuation"].plan.turns
        offset = step - len(prefix)
        return operator.execute(Decision(turn=turns[offset] if offset < len(turns) else Turn()))

    env = kaggle_environments.make(
        "kaggriculture",
        configuration={
            "episodeSteps": 70,
            "weedSpawnChance": 0,
            "townShopUnlockInterval": 10_000,
            "seed": 19,
        },
        debug=True,
    )
    env.run([agent, "pass"])
    return received, run


def _assert_interrupted_matches_environment(prefix_of):
    received, run = _play_interrupted(prefix_of)
    continuation = run["continuation"]
    start_step = len(run["prefix"])
    end = parse(received[start_step + len(continuation.plan.turns)])
    predicted = continuation.resulting_state

    assert (predicted.step, predicted.day, predicted.hour) == (end.step, end.day, end.hour)
    assert predicted.player == end.player
    assert predicted.opponent == end.opponent
    assert predicted.market == end.market
    assert predicted.town == end.town
    return run, end


@pytest.mark.parametrize(
    "point, n_of",
    [
        ("after BUY_SEED", lambda plan: _steps_of(plan, BUY_SEED)[0] + 1),
        ("after PLANT", lambda plan: _steps_of(plan, PLANT)[0] + 1),
        ("during growth", lambda plan: 30),
        ("harvestable", lambda plan: _steps_of(plan, HARVEST)[0]),
        ("after HARVEST", lambda plan: _steps_of(plan, HARVEST)[0] + 1),
    ],
)
def test_real_environment_interrupted_wheat_is_completed(point, n_of):
    run, end = _assert_interrupted_matches_environment(lambda plan: list(plan.turns[: n_of(plan)]))

    full = run["full"]
    n = len(run["prefix"])
    prefix_types = [a.action_type for turn in run["prefix"] for a in turn.actions()]
    combined = prefix_types + _types(run["continuation"].plan)
    assert combined.count(BUY_SEED) == 1 and combined.count(PLANT) == 1
    # The interrupted investment ends exactly where the uninterrupted plan would.
    assert end.step == len(full.plan.turns)
    assert end.player.money == full.resulting_state.player.money
    assert end.player.inventory.items["WHEAT"] == 0
    assert n < len(full.plan.turns)


def test_real_environment_drop_without_its_sale_is_sold():
    run, end = _assert_interrupted_matches_environment(lambda plan: _drop_without_sale(plan)[1])

    assert run["continuation"].plan.label == "sell WHEAT"
    assert end.player.inventory.items["WHEAT"] == 0


def test_real_environment_replanning_with_the_farmer_away_from_spawn():
    # Interrupt during growth after walking the farmer away from the plant.
    run, end = _assert_interrupted_matches_environment(
        lambda plan: list(plan.turns[:30]) + [Turn(farmer=Action(WEST)), Turn(farmer=Action(NORTH))]
    )

    assert run["continuation"].plan.label == "continue WHEAT at (4, 4)"
    assert end.player.money == run["full"].resulting_state.player.money
