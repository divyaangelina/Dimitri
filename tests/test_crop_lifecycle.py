"""Tests for WATER, HARVEST, and DROP, and the crop lifecycle they complete.

Rules come from the installed Kaggriculture environment
(``_apply_unit_action``, ``_is_shed_adjacent``, ``CROPS``):

- every farm-work op is ignored when the unit stands on a LOCKED tile;
- WATER needs an unwatered plant; a one-time crop watered from day
  ``(max_yield_day + 1) // 2`` to ``max_yield_day`` of its age gains 1
  yield (2 while fertilized), capped at ``max_yield``;
- HARVEST needs a plant with yield that is at least ``first_yield_day``
  days old; the yield goes to the unit's carried inventory, a one-time
  crop leaves an empty tile, and an ongoing crop stays with no yield;
- DROP needs a shed-access tile; carried items fill the shed up to its
  capacity, and anything left over is discarded.

Environment comparisons apply the environment's own ``_apply_unit_action``
to the raw observation, and full episodes play the lifecycle for real.
"""

import copy
import json
from pathlib import Path

import pytest

from dimitri.executive.decision import Decision
from dimitri.executive.executive import Executive
from dimitri.models.tile import PlantTile
from dimitri.observer.parser import parse
from dimitri.operator.operator import Operator
from dimitri.pipeline import Pipeline
from dimitri.planner.action import (
    DROP,
    HARVEST,
    MARKET_ACTION_TYPES,
    NORTH,
    PLANT,
    WATER,
    Action,
)
from dimitri.planner.generator import CandidateGenerator
from dimitri.planner.planner import Planner
from dimitri.planner.simulator import Simulator
from dimitri.planner.turn import Turn
from dimitri.utils.constants import CROPS

SAMPLE_OBSERVATION_PATH = Path(__file__).parent / "sample_observation.json"
SHED_TILE = (4, 4)  # The NW shed-access tile, unlocked from the start.
FIELD_TILE = (2, 2)
UNIT_OPS = (WATER, HARVEST, DROP)


def _plant(crop="WHEAT", planted_day=0, **fields):
    plant = {
        "kind": "PLANT",
        "crop": crop,
        "planted_day": planted_day,
        "watered_today": False,
        "consecutive_unwatered": 0,
        "yield_units": 1,
        "max_lifespan_step": 500,
        "fertilized_until_day": -1,
    }
    plant.update(fields)
    return plant


def _observation(
    *, day=3, farmer=FIELD_TILE, hands=(), tiles=None, shed=None, carried=None
):
    with SAMPLE_OBSERVATION_PATH.open() as f:
        observation = json.load(f)
    observation["day"], observation["hour"] = day, 5
    observation["step"] = day * 24 + 5
    farm = observation["farms"][observation["player"]]
    farm["farmer"] = list(farmer)
    farm["hands"] = [list(h) for h in hands]
    for (x, y), tile in (tiles or {}).items():
        farm["tiles"][y][x] = copy.deepcopy(tile)
    private = observation["private"]
    private["shed"] = {"EGG": 2} if shed is None else shed
    private["inventories"] = (
        [{} for _ in range(1 + len(hands))] if carried is None else carried
    )
    return observation


def _state(**kwargs):
    return parse(_observation(**kwargs))


def _do(state, op, unit=0):
    return Simulator().simulate(state, Action(op), unit=unit)


def _tile(state, position=FIELD_TILE):
    x, y = position
    return state.player.farm.tiles[y][x]


def _carried(state, unit=0):
    return dict(state.player.unit_inventories[unit].items)


# --- representation and the Operator -----------------------------------


def test_new_actions_use_api_names():
    assert (WATER, HARVEST, DROP) == ("WATER", "HARVEST", "DROP")
    assert not set(UNIT_OPS) & MARKET_ACTION_TYPES


@pytest.mark.parametrize("op", UNIT_OPS)
def test_new_actions_carry_no_target(op):
    action = Action(op)

    assert (action.target, action.quantity) == (None, 1)
    assert Turn.from_action(action) == Turn(farmer=action)


@pytest.mark.parametrize("op", UNIT_OPS)
def test_operator_writes_farmer_op_alone(op):
    api_action = Operator().execute(Decision(turn=Turn(farmer=Action(op))))

    assert api_action == {"farmer": [op], "hands": [], "market": []}


def test_operator_writes_hand_ops_in_hand_order():
    turn = Turn(
        farmer=Action(PLANT, "WHEAT"),
        hands=(Action(WATER), None, Action(HARVEST), Action(DROP)),
    )

    assert Operator().execute(Decision(turn=turn)) == {
        "farmer": ["PLANT", "WHEAT"],
        "hands": [["WATER"], ["PASS"], ["HARVEST"], ["DROP"]],
        "market": [],
    }


@pytest.mark.parametrize("op", UNIT_OPS)
@pytest.mark.parametrize(
    "action_kwargs", [{"target": "WHEAT"}, {"quantity": 2}, {"quantity": True}]
)
def test_operator_rejects_malformed_unit_op(op, action_kwargs):
    with pytest.raises(ValueError):
        Operator().to_unit_op(Action(op, **action_kwargs))


@pytest.mark.parametrize("op", UNIT_OPS)
def test_operator_rejects_unit_op_as_market_order(op):
    with pytest.raises(ValueError, match="Unsupported market action"):
        Operator().to_market_order(Action(op))


# --- crop rules ----------------------------------------------------------


def test_crop_rules_match_environment():
    env = pytest.importorskip("kaggle_environments.envs.kaggriculture.kaggriculture")

    for crop, rules in CROPS.items():
        raw = env.CROPS[crop]
        assert rules.first_yield_day == raw["first_yield_day"]
        assert rules.max_yield_day == raw["max_yield_day"]
        assert rules.max_yield == raw["max_yield"]
        assert rules.ongoing == raw["ongoing"]


# --- WATER ---------------------------------------------------------------


def test_water_marks_plant_watered():
    # Day 1 of a WHEAT's age is before its watering window (days 2-4).
    state = _state(day=1, tiles={FIELD_TILE: _plant(yield_units=1)})

    result = _do(state, WATER)

    assert _tile(result) == PlantTile(
        crop="WHEAT",
        planted_day=0,
        watered_today=True,
        consecutive_unwatered=0,
        yield_units=1,
        max_lifespan_step=500,
        fertilized_until_day=-1,
    )


@pytest.mark.parametrize(("day", "bonus"), [(1, 0), (2, 1), (3, 1), (4, 1), (5, 0)])
def test_water_adds_yield_only_inside_the_one_time_window(day, bonus):
    state = _state(day=day, tiles={FIELD_TILE: _plant(yield_units=1)})

    assert _tile(_do(state, WATER)).yield_units == 1 + bonus


def test_water_bonus_doubles_while_fertilized():
    state = _state(day=3, tiles={FIELD_TILE: _plant(fertilized_until_day=3)})

    assert _tile(_do(state, WATER)).yield_units == 1 + 2


def test_water_bonus_ends_after_fertilizer_expires():
    state = _state(day=3, tiles={FIELD_TILE: _plant(fertilized_until_day=2)})

    assert _tile(_do(state, WATER)).yield_units == 1 + 1


def test_water_bonus_is_capped_at_max_yield():
    state = _state(day=3, tiles={FIELD_TILE: _plant(yield_units=6)})

    assert _tile(_do(state, WATER)).yield_units == CROPS["WHEAT"].max_yield


def test_water_gives_ongoing_crop_no_yield():
    state = _state(day=8, tiles={FIELD_TILE: _plant("TOMATO", yield_units=0)})

    result = _do(state, WATER)

    assert _tile(result).watered_today is True
    assert _tile(result).yield_units == 0


def test_water_changes_only_the_plant_under_the_unit():
    state = _state(
        day=3, tiles={FIELD_TILE: _plant(), (0, 0): _plant(), (1, 0): {"kind": "WEED"}}
    )

    result = _do(state, WATER)

    for y, row in enumerate(state.player.farm.tiles):
        for x, tile in enumerate(row):
            if (x, y) != FIELD_TILE:
                assert result.player.farm.tiles[y][x] == tile
    assert result.player.money == state.player.money
    assert result.player.inventory == state.player.inventory
    assert result.player.unit_inventories == state.player.unit_inventories
    assert result.player.seeds == state.player.seeds
    assert result.player.farm.farmer == state.player.farm.farmer
    assert result.market == state.market


def test_hand_waters_its_own_tile():
    state = _state(day=3, hands=[(0, 0)], tiles={(0, 0): _plant(), FIELD_TILE: _plant()})

    result = _do(state, WATER, unit=1)

    assert _tile(result, (0, 0)).watered_today is True
    assert _tile(result, FIELD_TILE).watered_today is False


def test_water_already_watered_plant_raises():
    state = _state(tiles={FIELD_TILE: _plant(watered_today=True)})

    with pytest.raises(ValueError, match="already been watered"):
        _do(state, WATER)


@pytest.mark.parametrize(
    "tile", [None, "LOCKED", {"kind": "WEED"}, {"kind": "COOP"}]
)
def test_water_without_plant_raises(tile):
    with pytest.raises(ValueError, match="without a plant"):
        _do(_state(tiles={FIELD_TILE: tile}), WATER)


def test_water_by_missing_hand_raises():
    with pytest.raises(ValueError, match="does not exist"):
        _do(_state(tiles={FIELD_TILE: _plant()}), WATER, unit=1)


# --- HARVEST -------------------------------------------------------------


def test_harvest_one_time_crop_empties_tile_into_carried_inventory():
    state = _state(day=3, tiles={FIELD_TILE: _plant(yield_units=4)})

    result = _do(state, HARVEST)

    assert _tile(result) is None
    assert _carried(result) == {"WHEAT": 4}


def test_harvest_ongoing_crop_keeps_plant_with_no_yield():
    plant = _plant("TOMATO", yield_units=2, watered_today=True, max_lifespan_step=-1)
    state = _state(day=9, tiles={FIELD_TILE: plant})

    result = _do(state, HARVEST)

    assert _tile(result) == PlantTile(
        crop="TOMATO",
        planted_day=0,
        watered_today=True,
        consecutive_unwatered=0,
        yield_units=0,
        max_lifespan_step=-1,
        fertilized_until_day=-1,
    )
    assert _carried(result) == {"TOMATO": 2}


def test_harvest_adds_to_items_already_carried():
    state = _state(
        day=3, tiles={FIELD_TILE: _plant(yield_units=2)}, carried=[{"WHEAT": 1, "EGG": 3}]
    )

    assert _carried(_do(state, HARVEST)) == {"WHEAT": 3, "EGG": 3}


def test_harvest_leaves_money_shed_and_seeds_unchanged():
    state = _state(day=3, tiles={FIELD_TILE: _plant(yield_units=2)})

    result = _do(state, HARVEST)

    assert result.player.money == state.player.money
    assert result.player.inventory == state.player.inventory
    assert result.player.seeds == state.player.seeds
    assert result.market == state.market


def test_hand_harvests_into_its_own_inventory():
    state = _state(day=3, hands=[(0, 0)], tiles={(0, 0): _plant(yield_units=3)})

    result = _do(state, HARVEST, unit=1)

    assert _carried(result, 0) == {}
    assert _carried(result, 1) == {"WHEAT": 3}


def test_harvest_by_hand_without_inventory_entry_adds_one():
    # The environment grows the inventories list when a unit has no entry.
    state = _state(day=3, hands=[(0, 0)], tiles={(0, 0): _plant()}, carried=[{}])

    result = _do(state, HARVEST, unit=1)

    assert [dict(i.items) for i in result.player.unit_inventories] == [{}, {"WHEAT": 1}]


def test_harvest_before_first_yield_day_raises():
    # WHEAT is harvestable from day 2 of its age.
    state = _state(day=1, tiles={FIELD_TILE: _plant(yield_units=1)})

    with pytest.raises(ValueError, match="cannot be harvested before day 2"):
        _do(state, HARVEST)


def test_harvest_without_yield_raises():
    state = _state(day=9, tiles={FIELD_TILE: _plant("TOMATO", yield_units=0)})

    with pytest.raises(ValueError, match="no yield"):
        _do(state, HARVEST)


@pytest.mark.parametrize("tile", [None, "LOCKED", {"kind": "WEED"}, {"kind": "PASTURE"}])
def test_harvest_without_plant_raises(tile):
    with pytest.raises(ValueError, match="without a plant"):
        _do(_state(tiles={FIELD_TILE: tile}), HARVEST)


# --- DROP ----------------------------------------------------------------


def test_drop_moves_carried_items_into_shed():
    state = _state(farmer=SHED_TILE, shed={"EGG": 2}, carried=[{"WHEAT": 3, "EGG": 1}])

    result = _do(state, DROP)

    assert dict(result.player.inventory.items) == {"EGG": 3, "WHEAT": 3}
    assert _carried(result) == {}


def test_drop_discards_what_the_shed_cannot_hold():
    state = _state(farmer=SHED_TILE, shed={"EGG": 98}, carried=[{"WHEAT": 3, "MILK": 2}])

    result = _do(state, DROP)

    assert dict(result.player.inventory.items) == {"EGG": 98, "WHEAT": 2}
    assert _carried(result) == {}


def test_drop_into_full_shed_discards_everything():
    state = _state(farmer=SHED_TILE, shed={"EGG": 100}, carried=[{"WHEAT": 3}])

    result = _do(state, DROP)

    assert dict(result.player.inventory.items) == {"EGG": 100}
    assert _carried(result) == {}


def test_drop_empties_only_the_acting_unit():
    state = _state(
        hands=[SHED_TILE], shed={}, carried=[{"MILK": 1}, {"WHEAT": 2}]
    )

    result = _do(state, DROP, unit=1)

    assert dict(result.player.inventory.items) == {"WHEAT": 2}
    assert _carried(result, 0) == {"MILK": 1}
    assert _carried(result, 1) == {}


def test_drop_leaves_money_seeds_and_farm_unchanged():
    state = _state(farmer=SHED_TILE, carried=[{"WHEAT": 3}])

    result = _do(state, DROP)

    assert result.player.money == state.player.money
    assert result.player.seeds == state.player.seeds
    assert result.player.farm == state.player.farm
    assert result.market == state.market


def test_drop_away_from_shed_raises():
    state = _state(farmer=(3, 4), carried=[{"WHEAT": 3}])

    with pytest.raises(ValueError, match="not next to the shed"):
        _do(state, DROP)


def test_drop_on_locked_shed_access_tile_raises():
    # (5, 4) is the NE shed-access tile, locked until NE is bought.
    state = _state(farmer=(5, 4), carried=[{"WHEAT": 3}])

    with pytest.raises(ValueError, match="LOCKED"):
        _do(state, DROP)


def test_drop_on_unlocked_other_shed_access_tile():
    state = _state(farmer=(5, 5), tiles={(5, 5): None}, shed={}, carried=[{"WHEAT": 1}])

    assert dict(_do(state, DROP).player.inventory.items) == {"WHEAT": 1}


def test_drop_with_nothing_carried_raises():
    with pytest.raises(ValueError, match="carrying nothing"):
        _do(_state(farmer=SHED_TILE, carried=[{}]), DROP)


# --- shared validation and immutability ---------------------------------


@pytest.mark.parametrize("op", UNIT_OPS)
@pytest.mark.parametrize("action_kwargs", [{"target": "WHEAT"}, {"quantity": 2}])
def test_simulator_rejects_malformed_unit_op(op, action_kwargs):
    state = _state(farmer=SHED_TILE, tiles={SHED_TILE: _plant()}, carried=[{"EGG": 1}])

    with pytest.raises(ValueError):
        Simulator().simulate(state, Action(op, **action_kwargs))


@pytest.mark.parametrize("op", UNIT_OPS)
def test_unit_op_in_market_channel_is_rejected(op):
    with pytest.raises(ValueError, match="not a market action"):
        Simulator().simulate_turn(_state(), Turn(market=(Action(op),)))


@pytest.mark.parametrize("op", UNIT_OPS)
def test_unit_ops_do_not_mutate_original(op):
    state = _state(
        farmer=SHED_TILE, tiles={SHED_TILE: _plant(yield_units=2)}, carried=[{"EGG": 1}]
    )
    before = copy.deepcopy(state)

    _do(state, op)

    assert state == before


def test_turn_harvest_then_drop_by_different_units():
    state = _state(
        hands=[SHED_TILE],
        shed={},
        tiles={FIELD_TILE: _plant(yield_units=2)},
        carried=[{}, {"EGG": 1}],
    )
    turn = Turn(farmer=Action(HARVEST), hands=(Action(DROP),))

    result = Simulator().simulate_turn(state, turn)

    assert _carried(result, 0) == {"WHEAT": 2}
    assert dict(result.player.inventory.items) == {"EGG": 1}


# --- generation ----------------------------------------------------------


def _unit_ops(state):
    return [a for a in CandidateGenerator().generate(state) if a.action_type in UNIT_OPS]


def test_water_is_generated_for_unwatered_plant():
    assert _unit_ops(_state(day=1, tiles={FIELD_TILE: _plant()})) == [Action(WATER)]


def test_water_is_not_generated_for_watered_plant_or_empty_tile():
    assert _unit_ops(_state(day=1, tiles={FIELD_TILE: _plant(watered_today=True)})) == []
    assert _unit_ops(_state()) == []


def test_harvest_is_generated_only_when_ready():
    ready = _state(day=3, tiles={FIELD_TILE: _plant(watered_today=True)})
    young = _state(day=1, tiles={FIELD_TILE: _plant(watered_today=True)})
    empty = _state(day=3, tiles={FIELD_TILE: _plant(watered_today=True, yield_units=0)})

    assert _unit_ops(ready) == [Action(HARVEST)]
    assert _unit_ops(young) == []
    assert _unit_ops(empty) == []


def test_drop_is_generated_only_at_shed_while_carrying():
    assert _unit_ops(_state(farmer=SHED_TILE, carried=[{"WHEAT": 1}])) == [Action(DROP)]
    assert _unit_ops(_state(farmer=SHED_TILE, carried=[{}])) == []
    assert _unit_ops(_state(farmer=FIELD_TILE, carried=[{"WHEAT": 1}])) == []


def test_every_legal_unit_op_is_generated_together():
    state = _state(
        day=3, farmer=SHED_TILE, tiles={SHED_TILE: _plant()}, carried=[{"EGG": 1}]
    )

    assert _unit_ops(state) == [Action(WATER), Action(HARVEST), Action(DROP)]


def test_unit_op_generation_ignores_market_prices():
    state = _state(
        day=3, farmer=SHED_TILE, tiles={SHED_TILE: _plant()}, carried=[{"EGG": 1}]
    )
    repriced = copy.deepcopy(state)
    object.__setattr__(repriced.market, "prices", {})

    assert _unit_ops(repriced) == _unit_ops(state)


def test_generated_unit_ops_can_all_be_simulated():
    state = _state(
        day=3, farmer=SHED_TILE, tiles={SHED_TILE: _plant()}, carried=[{"EGG": 1}]
    )

    for action in _unit_ops(state):
        Simulator().simulate(state, action)


def test_planner_keeps_idle_turn_alongside_unit_ops():
    state = _state(day=3, tiles={FIELD_TILE: _plant()})

    turns = [c.turn for c in Planner().plan(state).candidates]

    assert Turn(farmer=Action(WATER)) in turns
    assert Turn(farmer=Action(HARVEST)) in turns
    assert turns[-1] == Turn()


class _PickFarmerOp(Executive):
    """Commits to the candidate whose farmer performs ``op``."""

    def __init__(self, op):
        self._op = op

    def decide(self, planning_result):
        for candidate in planning_result.candidates:
            if candidate.turn.farmer == Action(self._op):
                return Decision(turn=candidate.turn)
        raise AssertionError(f"no {self._op} candidate")


@pytest.mark.parametrize(
    ("op", "observation_kwargs"),
    [
        (WATER, {"tiles": {FIELD_TILE: _plant()}}),
        (HARVEST, {"tiles": {FIELD_TILE: _plant(watered_today=True)}}),
        (DROP, {"farmer": SHED_TILE, "carried": [{"WHEAT": 1}]}),
    ],
)
def test_unit_op_decision_flows_to_the_operator(op, observation_kwargs):
    observation = _observation(**observation_kwargs)

    api_action = Pipeline(executive=_PickFarmerOp(op)).run(observation)

    assert api_action == {"farmer": [op], "hands": [], "market": []}


# --- the real environment: single ops -----------------------------------


def _env_apply(observation, op, unit=0):
    """Apply ``op`` with the environment's own unit-action code; return the result."""
    env = pytest.importorskip("kaggle_environments.envs.kaggriculture.kaggriculture")
    raw = copy.deepcopy(observation)
    farm, private = raw["farms"][raw["player"]], raw["private"]
    env._apply_unit_action(farm, private, unit, [op], 10, raw["day"], 24, 100)
    return parse(raw)


_ENV_CASES = {
    "water before window": (WATER, {"day": 1, "tiles": {FIELD_TILE: _plant()}}),
    "water in window": (WATER, {"day": 3, "tiles": {FIELD_TILE: _plant()}}),
    "water fertilized": (
        WATER,
        {"day": 3, "tiles": {FIELD_TILE: _plant(fertilized_until_day=4)}},
    ),
    "water at max yield": (WATER, {"day": 3, "tiles": {FIELD_TILE: _plant(yield_units=6)}}),
    "water ongoing": (WATER, {"day": 9, "tiles": {FIELD_TILE: _plant("TOMATO")}}),
    "water melon window": (WATER, {"day": 6, "tiles": {FIELD_TILE: _plant("MELON")}}),
    "harvest one-time": (
        HARVEST,
        {"day": 3, "tiles": {FIELD_TILE: _plant(yield_units=4)}, "carried": [{"WHEAT": 1}]},
    ),
    "harvest ongoing": (
        HARVEST,
        {"day": 11, "tiles": {FIELD_TILE: _plant("STRAWBERRY", yield_units=2)}},
    ),
    "harvest by hand": (
        HARVEST,
        {"day": 3, "hands": [(0, 0)], "tiles": {(0, 0): _plant(yield_units=2)}},
        1,
    ),
    "drop": (DROP, {"farmer": SHED_TILE, "shed": {"EGG": 2}, "carried": [{"WHEAT": 3}]}),
    "drop overflow": (
        DROP,
        {"farmer": SHED_TILE, "shed": {"EGG": 98}, "carried": [{"WHEAT": 3, "MILK": 2}]},
    ),
    "drop by hand": (
        DROP,
        {"hands": [SHED_TILE], "shed": {}, "carried": [{"MILK": 1}, {"WHEAT": 2}]},
        1,
    ),
}


@pytest.mark.parametrize("case", sorted(_ENV_CASES))
def test_unit_op_matches_environment(case):
    op, kwargs, *unit = _ENV_CASES[case]
    unit = unit[0] if unit else 0
    observation = _observation(**kwargs)

    expected = _env_apply(observation, op, unit)
    predicted = Simulator().simulate(parse(observation), Action(op), unit=unit)

    assert predicted.player == expected.player


_ENV_NO_OPS = {
    "water watered plant": (WATER, {"tiles": {FIELD_TILE: _plant(watered_today=True)}}),
    "water empty tile": (WATER, {}),
    "harvest too young": (HARVEST, {"day": 1, "tiles": {FIELD_TILE: _plant()}}),
    "harvest no yield": (HARVEST, {"day": 9, "tiles": {FIELD_TILE: _plant("TOMATO", yield_units=0)}}),
    "harvest weed": (HARVEST, {"tiles": {FIELD_TILE: {"kind": "WEED"}}}),
    "drop away from shed": (DROP, {"carried": [{"WHEAT": 1}]}),
    "drop on locked access tile": (DROP, {"farmer": (5, 4), "carried": [{"WHEAT": 1}]}),
    "drop nothing": (DROP, {"farmer": SHED_TILE, "carried": [{}]}),
}


@pytest.mark.parametrize("case", sorted(_ENV_NO_OPS))
def test_environment_ignores_unit_ops_the_simulator_rejects(case):
    op, kwargs = _ENV_NO_OPS[case]
    observation = _observation(**kwargs)

    assert _env_apply(observation, op).player == parse(observation).player
    with pytest.raises(ValueError):
        Simulator().simulate(parse(observation), Action(op))


# --- the real environment: full lifecycles ------------------------------


def _play_lifecycle(plan, episode_steps):
    """Play ``plan`` ({step: (farmer_op, market_orders)}); return all observations."""
    kaggle_environments = pytest.importorskip("kaggle_environments")
    received = {}

    def agent(obs):
        received[obs["step"]] = copy.deepcopy(dict(obs))
        farmer, market = plan.get(obs["step"], (["PASS"], []))
        return {"farmer": farmer, "hands": [], "market": market}

    env = kaggle_environments.make(
        "kaggriculture",
        configuration={"episodeSteps": episode_steps, "seed": 3},
        debug=True,
    )
    env.run([agent, "pass"])
    return received


def _assert_plan_matches_simulation(plan, received):
    for step, (farmer, market) in sorted(plan.items()):
        assert step % 24 != 23, "end-of-day steps are not simulated"
        before, after = parse(received[step]), parse(received[step + 1])
        turn = Turn(
            farmer=None if farmer == ["PASS"] else Action(*farmer),
            market=tuple(Action(*order) for order in market),
        )

        predicted = Simulator().simulate_turn(before, turn)

        assert predicted.player == after.player, (step, farmer, market)


def test_wheat_lifecycle_matches_environment():
    # WHEAT planted on day 0 at the farmer's spawn, (4, 4), which is also
    # a shed-access tile. Watered each day; day 2 is inside its watering
    # window, so it gains a yield unit before being harvested.
    plan = {
        0: (["PASS"], [["BUY_SEED", "WHEAT", 1]]),
        1: (["PLANT", "WHEAT"], []),
        2: (["WATER"], []),
        25: (["WATER"], []),
        49: (["WATER"], []),
        50: (["HARVEST"], []),
        51: (["DROP"], []),
        52: (["PASS"], [["SELL", "WHEAT", 2]]),
    }

    received = _play_lifecycle(plan, episode_steps=56)

    _assert_plan_matches_simulation(plan, received)
    final = parse(received[53]).player
    assert final.seeds["WHEAT"] == 0
    assert final.farm.tiles[4][4] is None
    assert final.inventory.items["WHEAT"] == 0
    assert final.money > 3000 - 10


def test_ongoing_tomato_harvest_matches_environment():
    # TOMATO first yields at the end of day 7 (first_yield_day 8) and stays
    # planted after harvest. It must be watered daily or it becomes a weed.
    plan = {
        0: (["PASS"], [["BUY_SEED", "TOMATO", 1]]),
        1: (["PLANT", "TOMATO"], []),
        **{24 * day + 2: (["WATER"], []) for day in range(9)},
        24 * 8 + 3: (["HARVEST"], []),
        24 * 8 + 4: (["DROP"], []),
    }

    received = _play_lifecycle(plan, episode_steps=24 * 8 + 8)

    _assert_plan_matches_simulation(plan, received)
    final = parse(received[24 * 8 + 5]).player
    assert isinstance(final.farm.tiles[4][4], PlantTile)
    assert final.farm.tiles[4][4].yield_units == 0
    assert final.inventory.items["TOMATO"] == 1
