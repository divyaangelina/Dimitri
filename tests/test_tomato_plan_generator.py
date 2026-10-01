"""Tests for TomatoPlanGenerator: one TOMATO_PRODUCTION plan from the current state.

Tomato is an ongoing crop. A plant planted on day P produces one unit at
the end of days P+7 to P+10, harvesting does not remove it, and its
yield accumulates on the plant. From the current GameState the
generator continues a living tomato first, then sells tomatoes the
farmer carries or the shed holds, and only otherwise starts a new
tomato, using a held seed before buying one.

The plan's boundary is the plant's remaining useful productive life: it
waters the plant daily, harvests once on the day after its last
production that can still be sold by the season's last action, then
drops and sells. Near the season's end that is an earlier production
than the plant's last.

Real-environment tests play generated plans, or interrupt one and play
the plan generated again from the live observation, in the installed
Kaggriculture environment through the Operator, with random weeds and
town-shop unlocks switched off and a passing opponent.
"""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from dimitri.analyst.opportunity import Opportunity, OpportunityKind
from dimitri.executive.decision import Decision
from dimitri.models.tile import WeedTile
from dimitri.observer.parser import parse
from dimitri.operator.operator import Operator
from dimitri.planner import farm_scheduler
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
from dimitri.planner.plan_generator import (
    PlanGenerator,
    TomatoPlanGenerator,
    WheatPlanGenerator,
    living_plants,
    production_days,
)
from dimitri.planner.simulator import Simulator
from dimitri.planner.time_rules import plant_at_end_of_day
from dimitri.planner.turn import Turn
from dimitri.utils.constants import LAST_ACTION_STEP

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"
SPAWN = (4, 4)
TOMATO = Opportunity(OpportunityKind.TOMATO_PRODUCTION)
WEED = {"kind": "WEED"}


def _tomato(planted_day, *, watered=False, unwatered=0, yield_units=0, final=False, crop="TOMATO"):
    """A raw plant tile as the environment writes it; ``final`` once the last production set its lifespan."""
    return {
        "kind": "PLANT",
        "crop": crop,
        "planted_day": planted_day,
        "watered_today": watered,
        "consecutive_unwatered": unwatered,
        "yield_units": yield_units,
        "max_lifespan_step": (planted_day + 12) * 24 if final else -1,
        "fertilized_until_day": -1,
    }


def _wheat(planted_day):
    tile = _tomato(planted_day, yield_units=1, crop="WHEAT")
    tile["max_lifespan_step"] = (planted_day + 5) * 24
    return tile


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


def _one(**kwargs):
    """A state whose bank buys exactly one tomato seed, so a fresh wave is a single plant."""
    return _state(money=99, **kwargs)


def _generate(state, opportunity=TOMATO):
    return TomatoPlanGenerator().generate_with_states(state, opportunity)


def _generated(state):
    (generated,) = _generate(state)
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


def _sold(plan):
    return sum(a.quantity for a in plan.actions() if a.action_type == SELL)


def _final(state, plan):
    return Simulator().simulate_plan(state, plan)


def _prefix(state, plan, n):
    return Simulator().simulate_plan(state, Plan(TOMATO, turns=plan.turns[:n], horizon=n))


def _tile(state, xy):
    x, y = xy
    return state.player.farm.tiles[y][x]


# --- the PlanGenerator boundary -----------------------------------------


def test_tomato_generator_is_a_plan_generator_for_tomato():
    generator = TomatoPlanGenerator()

    assert isinstance(generator, PlanGenerator)
    assert generator.opportunity_kind is OpportunityKind.TOMATO_PRODUCTION


@pytest.mark.parametrize(
    "kind", [k for k in OpportunityKind if k is not OpportunityKind.TOMATO_PRODUCTION]
)
def test_unrelated_opportunities_produce_no_tomato_plan(kind):
    assert TomatoPlanGenerator().generate(_state(), Opportunity(kind)) == ()


def test_production_days_match_the_end_of_day_refresh():
    plant = _tile(_state(tiles={SPAWN: _tomato(3)}), SPAWN)
    produced, current = [], plant
    for day in range(3, 20):
        after = plant_at_end_of_day(current, day)
        if after.yield_units > current.yield_units:
            produced.append(day)
        current = replace(after, watered_today=True)

    assert production_days(plant) == tuple(produced) == (10, 11, 12, 13)


# --- a fresh tomato -----------------------------------------------------


def test_fresh_tomato_plan_from_the_start_of_the_game():
    plan = _plan(_one())

    assert plan.opportunity == TOMATO
    assert plan.label == "TOMATO at (4, 4)"
    assert plan.horizon == len(plan.turns) == 266
    assert _actions(plan) == [
        Action(BUY_SEED, "TOMATO", 1), Action(PLANT, "TOMATO"),
        *[Action(WATER)] * 11,
        Action(HARVEST), Action(DROP), Action(SELL, "TOMATO", 4),
    ]


def test_fresh_tomato_timing_follows_the_game_rules():
    plan = _plan(_one())

    assert _steps_of(plan, PLANT) == [1]
    # Watered on the planting day and every day up to the last production.
    assert _steps_of(plan, WATER) == [2, *(24 * d for d in range(1, 11))]
    # The last production is at the end of day 10: harvest on day 11.
    assert _steps_of(plan, HARVEST) == [24 * 11]
    # The drop is applied before the market, so the sale shares its turn.
    assert _steps_of(plan, DROP) == [24 * 11 + 1]
    assert _steps_of(plan, SELL) == [24 * 11 + 1]


def test_wave_seeds_are_all_bought_up_front_and_paid_once():
    state = _state()
    plan = _plan(state)
    (buy,) = plan.turns[0].market
    after_buy = _prefix(state, plan, 1)

    assert buy == Action(BUY_SEED, "TOMATO", buy.quantity)
    assert BUY_SEED not in [a.action_type for t in plan.turns[1:] for a in t.actions()]
    assert after_buy.player.money == state.player.money - 50 * buy.quantity
    assert after_buy.player.seeds["TOMATO"] == buy.quantity


def test_held_seeds_are_planted_as_the_wave_without_buying_another():
    # Held seeds are the unfinished wave: both are planted and none bought.
    state = _state(seeds={"TOMATO": 2})

    plan = _plan(state)
    final = _final(state, plan)

    assert plan.label == "TOMATO wave of 2"
    assert _types(plan)[0] == PLANT
    assert BUY_SEED not in _types(plan)
    assert _types(plan).count(PLANT) == 2
    assert final.player.seeds["TOMATO"] == 0


def test_plot_is_the_empty_tile_nearest_spawn():
    assert _plan(_one(tiles={SPAWN: WEED})).label == "TOMATO at (4, 3)"
    assert _plan(_one(tiles={SPAWN: WEED, (4, 3): WEED})).label == "TOMATO at (3, 4)"


def test_plot_away_from_spawn_is_walked_to_daily_and_back_to_drop():
    plan = _plan(_one(tiles={SPAWN: WEED}))

    moves = [a for a in plan.actions() if a.action_type in (NORTH, SOUTH)]
    # North on the planting day and on each later day; south back to drop.
    assert moves == [Action(NORTH)] * 12 + [Action(SOUTH)]


def test_fresh_plan_starts_from_the_farmers_current_position():
    plan = _plan(_one(farmer=(0, 0)))

    # The seed is bought while the farmer takes its first step.
    assert plan.turns[0] == Turn(farmer=Action(EAST), market=(Action(BUY_SEED, "TOMATO", 1),))
    assert [t.farmer for t in plan.turns[1:8]] == [Action(EAST)] * 3 + [Action(SOUTH)] * 4
    assert _steps_of(plan, PLANT) == [8]


@pytest.mark.parametrize("hour", [0, 21, 22, 23])
def test_planting_always_leaves_a_turn_to_water_the_same_day(hour):
    start = 24 * 3 + hour
    plan = _plan(_state(step=start))

    plant_steps = _steps_of(plan, PLANT, start_step=start)
    assert plant_steps
    for plant_step in plant_steps:
        # Every new plant is watered on the very next turn, the same day.
        assert plant_step % 24 < 23
        assert plan.turns[plant_step + 1 - start].farmer == Action(WATER)


def test_plan_reaches_the_first_production():
    state = _state()
    plan = _plan(state)

    on_day_8 = _prefix(state, plan, 24 * 8)
    assert _tile(on_day_8, SPAWN).yield_units == 1


def test_plan_ends_with_every_production_sold():
    state = _one()
    final = _final(state, _plan(state))

    assert final.player.inventory.items["TOMATO"] == 0
    assert all(not inv.items for inv in final.player.unit_inventories)
    assert final.player.money == state.player.money - 50 + 4 * 63
    # The spent plant is left with nothing on it; it decays later.
    assert _tile(final, SPAWN).yield_units == 0


def test_no_plan_without_money_for_a_seed():
    state = _state()
    state = replace(state, player=replace(state.player, money=49))

    assert _generate(state) == ()


def test_no_plan_without_an_empty_tile():
    tiles = {(x, y): WEED for x in range(5) for y in range(5)}

    assert _generate(_state(tiles=tiles)) == ()


# --- a living tomato ----------------------------------------------------


def test_newly_planted_unwatered_tomato_is_watered_first():
    state = _state(step=5, tiles={SPAWN: _tomato(0, unwatered=1)})

    plan = _plan(state)

    assert plan.label == "continue TOMATO at (4, 4)"
    assert plan.turns[0] == Turn(farmer=Action(WATER))
    assert BUY_SEED not in _types(plan) and PLANT not in _types(plan)
    assert _sold(plan) == 4


def test_living_tomato_and_held_seeds_are_continued_as_one_wave():
    # The held seed is the unfinished part of the wave: planted, not bought again.
    state = _state(step=5, tiles={SPAWN: _tomato(0, unwatered=1)}, seeds={"TOMATO": 1})

    plan = _plan(state)
    final = _final(state, plan)

    assert plan.label == "continue TOMATO wave of 2"
    assert plan.turns[0] == Turn(farmer=Action(WATER))
    assert BUY_SEED not in _types(plan)
    assert _types(plan).count(PLANT) == 1
    assert final.player.seeds["TOMATO"] == 0
    assert _sold(plan) == 8


def test_tomato_watered_today_is_not_watered_again():
    state = _state(step=5, tiles={SPAWN: _tomato(0, watered=True, unwatered=1)})

    plan = _plan(state)

    assert plan.turns[0] == Turn()
    assert _steps_of(plan, WATER, start_step=5)[0] == 24


def test_tomato_before_its_first_production_is_tended_to_the_end():
    state = _state(step=24 * 5 + 3, tiles={SPAWN: _tomato(0)})

    plan = _plan(state)

    assert _steps_of(plan, WATER, start_step=123) == [123, *(24 * d for d in range(6, 11))]
    assert _actions(plan)[-3:] == [Action(HARVEST), Action(DROP), Action(SELL, "TOMATO", 4)]


def test_yield_on_the_plant_is_kept_and_sold_with_later_production():
    # First production happened; its unit stays on the plant until day 11.
    state = _state(step=24 * 8 + 1, tiles={SPAWN: _tomato(0, yield_units=1)})

    plan = _plan(state)

    assert _steps_of(plan, HARVEST, start_step=193) == [24 * 11]
    assert _sold(plan) == 4


def test_tomato_after_one_harvest_sells_its_remaining_productions():
    # Harvested on day 8; the day-8 production has since added one unit.
    state = _state(step=24 * 9 + 1, tiles={SPAWN: _tomato(0, yield_units=1)})

    assert _sold(_plan(state)) == 3


def test_tomato_between_later_productions():
    state = _state(step=24 * 10 + 5, tiles={SPAWN: _tomato(0, watered=True, yield_units=3)})

    plan = _plan(state)

    assert _types(plan) == [HARVEST, DROP, SELL]
    assert _steps_of(plan, HARVEST, start_step=245) == [24 * 11]
    assert _sold(plan) == 4


def test_tomato_after_its_final_production_is_harvested_without_watering():
    state = _state(step=24 * 11, tiles={SPAWN: _tomato(0, yield_units=4, final=True)})

    assert _actions(_plan(state)) == [Action(HARVEST), Action(DROP), Action(SELL, "TOMATO", 4)]


def test_tomato_about_to_decay_is_harvested_before_it_loses_yield():
    # Decay starts at step 288. Harvested at hour 23, the night drops it.
    state = _state(step=287, tiles={SPAWN: _tomato(0, watered=True, yield_units=4, final=True)})

    plan = _plan(state)

    assert _actions(plan) == [Action(HARVEST), Action(SELL, "TOMATO", 4)]


def test_decaying_tomato_with_yield_is_harvested_at_once():
    state = _state(step=289, tiles={SPAWN: _tomato(0, yield_units=3, final=True)})

    assert _actions(_plan(state)) == [Action(HARVEST), Action(DROP), Action(SELL, "TOMATO", 3)]


def test_tomato_at_its_yield_cap_is_harvested_early_so_production_is_not_lost():
    # A full plant (possible with fertilizer) would waste further production.
    state = _state(step=24 * 9 + 1, tiles={SPAWN: _tomato(0, yield_units=4)})

    plan = _plan(state)

    assert _types(plan)[0] == HARVEST
    assert _sold(plan) == 4 + 2


def test_spent_tomato_is_not_continued():
    # Every production harvested and sold: nothing is left to continue.
    state = _one(step=24 * 11 + 3, tiles={SPAWN: _tomato(0, watered=True, final=True)})

    assert _plan(state).label == "TOMATO at (4, 3)"


def test_weed_is_not_continued():
    plan = _plan(_one(step=24, tiles={SPAWN: WEED}))

    assert plan.label == "TOMATO at (4, 3)"
    assert plan.turns[0].market == (Action(BUY_SEED, "TOMATO", 1),)


def test_tomato_that_cannot_be_saved_is_not_continued():
    # Planted today, still unwatered at hour 23 and out of reach.
    state = _one(step=23, tiles={(0, 0): _tomato(0, unwatered=1)})

    assert _plan(state).label == "TOMATO at (4, 4)"


def test_living_tomato_is_continued_from_a_distance():
    state = _state(step=24 * 11 + 2, farmer=(1, 1), tiles={(2, 3): _tomato(0, yield_units=4, final=True)})

    assert _actions(_plan(state)) == [
        Action(EAST), Action(SOUTH), Action(SOUTH), Action(HARVEST),
        Action(EAST), Action(EAST), Action(SOUTH), Action(DROP), Action(SELL, "TOMATO", 4),
    ]


# --- liquidation --------------------------------------------------------


def test_carried_tomatoes_are_dropped_and_sold():
    state = _state(step=265, farmer=(4, 3), carried={"TOMATO": 4})

    plan = _plan(state)

    assert plan.label == "sell TOMATO"
    assert _actions(plan) == [Action(SOUTH), Action(DROP), Action(SELL, "TOMATO", 4)]


def test_shed_tomatoes_are_sold():
    plan = _plan(_state(step=266, shed={"TOMATO": 4}))

    assert plan.label == "sell TOMATO"
    assert plan.turns == (Turn(market=(Action(SELL, "TOMATO", 4),)),)


def test_carried_tomatoes_are_sold_before_a_fresh_tomato_is_started():
    # (Held tomato seeds would be an unfinished program, continued first:
    # see test_tomato_program.py.)
    state = _state(step=30, carried={"TOMATO": 1}, shed={"TOMATO": 2})

    assert _actions(_plan(state)) == [Action(DROP), Action(SELL, "TOMATO", 3)]


def test_living_tomato_plan_also_sells_tomatoes_already_held():
    state = _state(step=24 * 11, tiles={SPAWN: _tomato(0, yield_units=4, final=True)}, shed={"TOMATO": 5})

    assert _actions(_plan(state))[-1] == Action(SELL, "TOMATO", 9)


def test_goods_of_other_crops_are_sold_and_other_goods_kept():
    # The plan's final sale sells every WHEAT and TOMATO in the shed, so
    # background wheat harvested during the plan reaches the bank; other
    # goods are not the scheduler's to sell.
    state = _state(shed={"WHEAT": 3, "EGG": 2})

    final = _final(state, _plan(state))

    assert final.player.inventory.items["WHEAT"] == 0
    assert final.player.inventory.items["EGG"] == 2


# --- replanning ---------------------------------------------------------


def _scenario(tiles):
    start = _state(tiles=tiles)
    plan = _plan(start)
    return start, plan, _final(start, plan)


def _assert_continuation_completes_the_investment(start, plan, full_final, n):
    generated = _generated(_prefix(start, plan, n))
    final = generated.resulting_state

    assert (final.step, final.player, final.market) == (full_final.step, full_final.player, full_final.market)
    combined = [a.action_type for turn in plan.turns[:n] for a in turn.actions()] + _types(generated.plan)
    assert combined.count(BUY_SEED) == 1
    assert combined.count(PLANT) == _types(plan).count(PLANT)
    return generated.plan


REPLANNING_POINTS = {
    "after BUY_SEED": lambda plan: _steps_of(plan, BUY_SEED)[0] + 1,
    "after the first PLANT": lambda plan: _steps_of(plan, PLANT)[0] + 1,
    "midway through the first planting day": lambda plan: 12,
    "with wave seeds still held": lambda plan: _steps_of(plan, PLANT)[2] + 1,
    "after the last PLANT": lambda plan: _steps_of(plan, PLANT)[-1] + 1,
    "during watering": lambda plan: 24 * 4 + 5,
    "during production": lambda plan: 24 * 9 + 12,
    "after the first HARVEST": lambda plan: _steps_of(plan, HARVEST)[0] + 1,
    "after the last HARVEST": lambda plan: _steps_of(plan, HARVEST)[-1] + 1,
}

BACKGROUND_WHEAT = {(0, 0): _wheat(0) | {"consecutive_unwatered": 1, "watered_today": False}}


@pytest.mark.parametrize(
    "tiles", [{}, BACKGROUND_WHEAT], ids=["wave alone", "wave with background wheat"]
)
@pytest.mark.parametrize("point", list(REPLANNING_POINTS))
def test_replanning_at_a_lifecycle_point_completes_the_same_investment(tiles, point):
    start, plan, full_final = _scenario(tiles)

    n = REPLANNING_POINTS[point](plan)
    continuation = _assert_continuation_completes_the_investment(start, plan, full_final, n)

    if PLANT not in [a.action_type for t in plan.turns[:n] for a in t.actions()]:
        # Only seeds held so far: they are the wave, planted without buying.
        assert continuation.label == plan.label
    elif point == "after the last HARVEST":
        assert continuation.label == "sell TOMATO"
    else:
        assert continuation.label.startswith("continue TOMATO wave of ")


def test_background_wheat_survives_the_uninterrupted_and_replanned_wave():
    start, plan, full_final = _scenario(BACKGROUND_WHEAT)

    # Harvested (an empty tile, not a weed) and sold, on both paths.
    assert _tile(full_final, (0, 0)) is None
    assert full_final.player.inventory.items["WHEAT"] == 0
    for n in (1, 30, 24 * 2):
        replanned = _generated(_prefix(start, plan, n)).resulting_state
        assert _tile(replanned, (0, 0)) is None
        assert replanned.player == full_final.player


@pytest.mark.parametrize(
    "tiles", [{}, BACKGROUND_WHEAT], ids=["wave alone", "wave with background wheat"]
)
def test_replanning_throughout_the_plan_completes_the_same_investment(tiles):
    start, plan, full_final = _scenario(tiles)

    for n in range(0, len(plan.turns), 7):
        _assert_continuation_completes_the_investment(start, plan, full_final, n)


# --- the season's end ---------------------------------------------------


@pytest.mark.parametrize(("day", "productions"), [(18, 4), (19, 3), (20, 2), (21, 1)])
def test_late_fresh_tomato_sells_only_the_productions_that_fit(day, productions):
    start = 24 * day
    plan = _plan(_one(step=start))

    assert _sold(plan) == productions
    # The harvest is on day 29; the sale lands by the last action step.
    assert _steps_of(plan, HARVEST, start_step=start) == [24 * 29]
    assert start + len(plan.turns) - 1 <= LAST_ACTION_STEP


def test_no_fresh_tomato_without_time_for_a_production():
    assert _generate(_state(step=24 * 22)) == ()


def test_no_fresh_tomato_when_planting_slips_to_a_day_too_late():
    # Day 21 hour 22: the seed is bought at hour 22, planting at hour 23
    # would leave no turn to water, and planting on day 22 is too late.
    assert _plan(_one(step=24 * 21 + 21)).label == "TOMATO at (4, 4)"
    assert _generate(_one(step=24 * 21 + 22)) == ()


@pytest.mark.parametrize("step", [0, 24 * 7 + 13, 24 * 17 + 22, 24 * 19 + 23, 24 * 21 + 21])
def test_plans_never_run_past_the_last_action_step(step):
    plan = _plan(_state(step=step))

    assert step + len(plan.turns) - 1 <= LAST_ACTION_STEP


def test_living_tomato_late_in_the_season_sells_its_in_season_productions():
    # Planted on day 20: only the day-27 and day-28 productions are refreshed in season.
    state = _state(step=24 * 27 + 1, tiles={SPAWN: _tomato(20)})

    plan = _plan(state)

    assert _sold(plan) == 2
    assert _steps_of(plan, SELL, start_step=state.step) == [24 * 29 + 1]


def test_final_harvest_still_drops_and_sells_by_the_last_action_step():
    state = _state(step=716, tiles={SPAWN: _tomato(18, watered=True, yield_units=4)})

    plan = _plan(state)

    assert _actions(plan) == [Action(HARVEST), Action(DROP), Action(SELL, "TOMATO", 4)]
    assert _steps_of(plan, SELL, start_step=716) == [717]


def test_harvest_on_the_second_last_action_still_sells_in_the_drop_turn():
    state = _state(step=717, tiles={SPAWN: _tomato(18, watered=True, yield_units=4)})

    plan = _plan(state)

    assert _steps_of(plan, SELL, start_step=717) == [LAST_ACTION_STEP]


def test_harvest_that_cannot_be_sold_in_time_gives_no_plan():
    state = _state(step=LAST_ACTION_STEP, tiles={SPAWN: _tomato(18, watered=True, yield_units=4)})

    assert _generate(state) == ()


def test_production_after_the_season_is_ignored():
    # Planted on day 22: its first production would be at the end of day 29, never refreshed.
    state = _state(step=24 * 25 + 1, tiles={SPAWN: _tomato(22)})

    assert _generate(state) == ()


def test_an_earlier_production_is_harvested_when_the_last_one_cannot_be_sold(monkeypatch):
    # With the season shortened to step 701, the day-28 production is
    # still refreshed (step 695) but its day-29 harvest at (0, 0) cannot be
    # walked back and sold by step 701; harvesting on day 28 can.
    monkeypatch.setattr(farm_scheduler, "LAST_ACTION_STEP", 24 * 29 + 5)
    state = _state(step=24 * 28 + 1, tiles={(0, 0): _tomato(18, yield_units=3)})

    plan = _plan(state)

    assert _steps_of(plan, HARVEST, start_step=state.step)[0] // 24 == 28
    assert _sold(plan) == 3


def test_unsellable_tomatoes_are_not_counted_as_terminal_cash():
    state = _state(step=LAST_ACTION_STEP, tiles={SPAWN: _tomato(18, watered=True, yield_units=4)})

    evaluation = ContinuationEvaluator().evaluate(state)

    assert evaluation.projected_terminal_cash == state.player.money
    assert evaluation.plans == ()


# --- several living tomatoes and other crops ----------------------------


def test_every_living_tomato_is_continued_together():
    state = _state(step=24 + 2, tiles={SPAWN: _tomato(1, watered=True), (0, 0): _tomato(0, watered=True)})

    assert _plan(state).label == "continue TOMATO wave of 2"
    assert living_plants(state, "TOMATO") == [(0, 0), (4, 4)]


def test_equally_near_jobs_are_done_by_row_then_column():
    state = _state(step=24 + 2, tiles={(3, 4): _tomato(0), (4, 3): _tomato(0)})

    plan = _plan(state)

    # Both need water and are one step away: (4, 3) is in the lower row.
    assert [t.farmer for t in plan.turns[:4]] == [
        Action(NORTH), Action(WATER), Action(WEST), Action(SOUTH),
    ]


def test_every_living_tomato_survives_the_plan():
    state = _state(step=2, tiles={(4, 3): _tomato(0, watered=True), SPAWN: _tomato(0, watered=True)})

    (generated,) = _generate(state)

    assert not any(isinstance(_tile(generated.resulting_state, xy), WeedTile) for xy in ((4, 3), SPAWN))
    assert _sold(generated.plan) == 8


def test_tomato_that_cannot_be_saved_gives_way_to_the_next():
    state = _state(step=23, tiles={(0, 0): _tomato(0, unwatered=1), (4, 3): _tomato(0, watered=True)})

    assert _plan(state).label == "continue TOMATO at (4, 3)"


def test_living_wheat_survives_a_tomato_plan_and_is_sold():
    state = _state(step=2, tiles={SPAWN: _tomato(0, watered=True), (4, 3): _wheat(0)})

    (generated,) = _generate(state)
    final = generated.resulting_state

    assert _tile(final, (4, 3)) is None  # harvested, not a weed
    assert final.player.inventory.items["WHEAT"] == 0
    assert final.player.money > state.player.money


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"seeds": {"TOMATO": 3}},
        {"step": 5, "tiles": {(x, 0): _tomato(0, watered=True) for x in range(5)}},
        {"step": 265, "carried": {"TOMATO": 4}, "shed": {"TOMATO": 2}},
        {"step": 24 * 22},
    ],
    ids=["fresh", "seeds", "several plants", "held tomatoes", "too late"],
)
def test_at_most_one_tomato_plan_per_state(kwargs):
    assert len(TomatoPlanGenerator().generate(_state(**kwargs), TOMATO)) <= 1


# --- state reuse and purity ---------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"seeds": {"TOMATO": 1}},
        {"step": 24 * 8 + 1, "tiles": {SPAWN: _tomato(0, yield_units=1)}},
        {"step": 265, "farmer": (4, 3), "carried": {"TOMATO": 4}},
        {"step": 266, "shed": {"TOMATO": 4}},
        {"step": 24 * 19},
    ],
    ids=["fresh", "held seed", "living tomato", "carried", "shed", "late season"],
)
def test_generated_state_is_reused_not_replayed(kwargs, monkeypatch):
    state = _state(**kwargs)
    expected = _final(state, _plan(state))

    def _refuse(*args, **kwargs):
        raise AssertionError("generation must not replay the finished plan")

    monkeypatch.setattr(Simulator, "simulate_plan", _refuse)

    assert _generated(state).resulting_state == expected


def test_generation_does_not_mutate_the_state():
    state = _state(step=50, farmer=(0, 0), tiles={(4, 3): _tomato(0, watered=True)}, carried={"TOMATO": 1})
    before = copy.deepcopy(state)

    _generate(state)

    assert state == before


def test_generation_is_deterministic():
    assert _generate(_state()) == _generate(_state())


def test_plan_carries_no_score():
    plan = _plan(_state())

    assert not any(hasattr(plan, name) for name in ("score", "expected_profit", "roi", "risk"))


# --- continuation evaluation --------------------------------------------


def test_continuation_evaluation_keeps_a_tomato_holding_yield():
    # Whichever hypothesis wins first, the shared scheduler harvests and
    # sells the tomato's yield in that plan rather than letting it decay.
    state = _state(step=24 * 11, tiles={SPAWN: _tomato(0, yield_units=4, final=True)})

    evaluation = ContinuationEvaluator().evaluate(state)
    first = evaluation.plans[0]

    assert Action(SELL, "TOMATO", 4) in first.actions()
    # Harvested, then left to decay naturally once spent.
    assert getattr(_tile(_final(state, first), SPAWN), "yield_units", 0) == 0
    assert evaluation.projected_terminal_cash > state.player.money


def test_continuation_evaluation_explores_every_wheat_and_tomato_sequence():
    """Record (previous plan's crop, next plan's crop) for every branch explored."""
    produced_by = {}
    pairs = set()

    class _Spy(PlanGenerator):
        def __init__(self, inner):
            self._inner = inner
            self.opportunity_kind = inner.opportunity_kind

        def generate(self, game_state, opportunity):
            return tuple(g.plan for g in self.generate_with_states(game_state, opportunity))

        def generate_with_states(self, game_state, opportunity):
            generated = self._inner.generate_with_states(game_state, opportunity)
            for g in generated:
                previous = produced_by.get(id(game_state))
                if previous is not None:
                    pairs.add((previous, self.opportunity_kind))
                produced_by[id(g.resulting_state)] = self.opportunity_kind
            return generated

    wheat, tomato = OpportunityKind.WHEAT_PRODUCTION, OpportunityKind.TOMATO_PRODUCTION
    # With little money a program is small, so another can follow it.
    ContinuationEvaluator(
        generators=[_Spy(WheatPlanGenerator()), _Spy(TomatoPlanGenerator())]
    ).evaluate(_state(step=24 * 4, money=249))

    assert pairs == {(wheat, wheat), (wheat, tomato), (tomato, wheat), (tomato, tomato)}


# --- the real environment -----------------------------------------------


def _play_interrupted(prefix_of):
    """Play part of a fresh tomato plan, replan from the live observation, and play the result.

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
            run["replan"] = _generated(parse(received[step]))
        turns = run["replan"].plan.turns
        offset = step - len(prefix)
        return operator.execute(Decision(turn=turns[offset] if offset < len(turns) else Turn()))

    # The whole season, so even a plan selling on the last action step is observed.
    steps = LAST_ACTION_STEP + 2
    env = kaggle_environments.make(
        "kaggriculture",
        configuration={
            "episodeSteps": steps,
            "weedSpawnChance": 0,
            "townShopUnlockInterval": 10_000,
            "seed": 23,
        },
        debug=True,
    )
    env.run([agent, "pass"])
    # The agent is not called on the season's final step; take it from the replay.
    final = env.steps[-1][0].observation
    received.setdefault(final["step"], copy.deepcopy(dict(final)))
    return received, run


def _assert_replan_matches_environment(prefix_of):
    received, run = _play_interrupted(prefix_of)
    replan = run["replan"]
    end = parse(received[len(run["prefix"]) + len(replan.plan.turns)])
    predicted = replan.resulting_state

    assert (predicted.step, predicted.day, predicted.hour) == (end.step, end.day, end.hour)
    assert predicted.player == end.player
    assert predicted.opponent == end.opponent
    assert predicted.market == end.market
    assert predicted.town == end.town
    return run, end


def test_real_environment_capacity_wave_from_the_start():
    run, end = _assert_replan_matches_environment(lambda plan: [])

    plan = run["replan"].plan
    planted = _types(plan).count(PLANT)
    assert plan.label == f"TOMATO wave of {planted}" and planted > 1
    assert _sold(plan) == 4 * planted
    assert end.player.inventory.items["TOMATO"] == 0
    assert end.player.money > 3000


@pytest.mark.parametrize(
    "point",
    [
        "after BUY_SEED",
        "after the first PLANT",
        "with wave seeds still held",
        "during watering",
        "during production",
        "after the first HARVEST",
        "after the last HARVEST",
    ],
)
def test_real_environment_interrupted_wave_is_completed(point):
    run, end = _assert_replan_matches_environment(
        lambda plan: list(plan.turns[: REPLANNING_POINTS[point](plan)])
    )

    full = run["full"]
    combined = [a.action_type for t in run["prefix"] for a in t.actions()] + _types(run["replan"].plan)
    assert combined.count(BUY_SEED) == 1
    assert combined.count(PLANT) == _types(full.plan).count(PLANT)
    assert end.step == len(full.plan.turns)
    assert end.player.money == full.resulting_state.player.money


def test_real_environment_late_season_wave_sells_part_of_its_lifecycle():
    # Idle until day 19, then plant: at most three productions fit the season.
    run, end = _assert_replan_matches_environment(lambda plan: [Turn()] * (24 * 19))

    plan = run["replan"].plan
    planted = _types(plan).count(PLANT)
    assert planted > 1
    assert planted < _sold(plan) <= 3 * planted
    assert end.player.inventory.items["TOMATO"] == 0
    assert end.step <= LAST_ACTION_STEP + 1


def _single_tomato_until(step):
    """Buy, plant and water one tomato daily on the spawn tile, never harvesting, until ``step``."""
    turns = [Turn(market=(Action(BUY_SEED, "TOMATO", 1),)), Turn(farmer=Action(PLANT, "TOMATO")), Turn(farmer=Action(WATER))]
    while len(turns) < step:
        turns.append(Turn(farmer=Action(WATER)) if len(turns) % 24 == 0 and len(turns) < 24 * 11 else Turn())
    return turns


def test_real_environment_decaying_tomato_is_harvested():
    # Tend one plant but skip its harvest; replan once decay has begun.
    run, end = _assert_replan_matches_environment(lambda plan: _single_tomato_until(24 * 12 + 1))

    assert _types(run["replan"].plan) == [HARVEST, DROP, SELL]
    assert _sold(run["replan"].plan) == 3
    assert end.player.inventory.items["TOMATO"] == 0


def test_real_environment_replanning_with_the_farmer_away_from_the_wave():
    run, end = _assert_replan_matches_environment(
        lambda plan: list(plan.turns[: 24 * 9 + 12]) + [Turn(farmer=Action(WEST)), Turn(farmer=Action(NORTH))]
    )

    assert run["replan"].plan.label.startswith("continue TOMATO wave of ")
    assert end.player.money == run["full"].resulting_state.player.money
