"""Kaggriculture's rules for the passage of time.

After every unit action and market order in a turn has been applied,
the environment's ``interpreter`` finishes the turn in this order:

1. Town consumption (``_town_consume``): every TOWN_SHOP_SELL_INTERVAL
   steps each unlocked shop removes its products from the market, and
   every TOWN_CENTER_SELL_INTERVAL steps the town center removes every
   product but FERTILIZER. Every step, all prices are then refreshed
   from market inventory.
2. Plant decay (``_decay_plants``), on both farms.
3. On the last turn of a day, the end-of-day sweep (``_end_of_day``),
   on both farms: plants and animals are refreshed, carried inventories
   are dropped into the shed, the farmer returns to the spawn tile,
   hands are dismissed, and ``hires_today`` resets.
4. ``step`` advances by one; ``day`` and ``hour`` follow from it.

These functions state those rules for one tile, farm, or market. They
mirror the installed environment and make no judgement about whether
any state is good.

Two end-of-day effects are random, drawn from the episode's hidden
seed, and are not modelled: weeds spawning on empty tiles
(``_spawn_weeds``) and the periodic unlock of a new town shop.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace

from dimitri.models.farm import Farm, TileValue
from dimitri.models.tile import AnimalTile, PlantTile, StructureTile, WeedTile
from dimitri.planner.rules import market_price
from dimitri.utils.constants import (
    ANIMALS,
    CROPS,
    PRODUCTS,
    SHOPS,
    TOWN_CENTER_DEMAND_SCHEDULE,
    TOWN_CENTER_SELL_INTERVAL,
    TOWN_SHOP_SELL_INTERVAL,
    TURNS_PER_DAY,
)

TOWN_CENTER_PRODUCTS = tuple(p for p in PRODUCTS if p != "FERTILIZER")
"""The products the town center consumes."""


def is_last_turn_of_day(step: int) -> bool:
    """Return whether the end-of-day sweep runs after the turn at ``step``."""
    return (step + 1) % TURNS_PER_DAY == 0


def spawn_position(farm: Farm) -> list[int]:
    """Return where the farmer stands at the start of each day.

    It is the NW shed-access tile, the first of the shed-access tiles
    in the environment's NW, NE, SW, SE order that lies in the NW
    quadrant.
    """
    half = len(farm.tiles) // 2
    return [half - 1, half - 1]


# --- market --------------------------------------------------------------


def town_consumption(
    step: int, day: int, unlocked_shops: Sequence[str]
) -> dict[str, int]:
    """Return how many units of each product the town removes from the market at ``step``.

    A shop selling a single product consumes 2 of it; any other shop
    consumes 1 of each of its products. The town center's demand grows
    with the day, per TOWN_CENTER_DEMAND_SCHEDULE.
    """
    consumed: dict[str, int] = {}
    if step % TOWN_SHOP_SELL_INTERVAL == 0:
        for shop in unlocked_shops:
            products = SHOPS[shop]
            units = 2 if len(products) == 1 else 1
            for item in products:
                consumed[item] = consumed.get(item, 0) + units
    if step % TOWN_CENTER_SELL_INTERVAL == 0:
        units = next(u for from_day, u in TOWN_CENTER_DEMAND_SCHEDULE if day >= from_day)
        for item in TOWN_CENTER_PRODUCTS:
            consumed[item] = consumed.get(item, 0) + units
    return consumed


def refreshed_prices(
    prices: Mapping[str, int], inventory: Mapping[str, int]
) -> dict[str, int]:
    """Return ``prices`` with every market product repriced from ``inventory``."""
    prices = dict(prices)
    for item in PRODUCTS:
        if item in inventory:
            prices[item] = market_price(item, inventory[item])
    return prices


# --- plants and animals --------------------------------------------------


def decays_at(tile: TileValue, step: int) -> bool:
    """Return whether the environment's decay changes ``tile`` at ``step``.

    Only a plant decays: from its ``max_lifespan_step`` on, on that step
    and every second step after it. A plant with no lifespan set (``-1``)
    and every other tile never do.
    """
    if not isinstance(tile, PlantTile):
        return False
    lifespan = tile.max_lifespan_step
    return 0 <= lifespan <= step and (step - lifespan) % 2 == 0


def decayed_tile(tile: TileValue, step: int) -> TileValue:
    """Return ``tile`` after the environment's decay at ``step``.

    A plant that decays at ``step`` (see ``decays_at``) loses one yield
    unit, becoming a weed when its yield reaches 0. Every other tile is
    returned unchanged.
    """
    if not decays_at(tile, step):
        return tile
    yield_units = tile.yield_units - 1
    if yield_units <= 0:
        return WeedTile()
    return replace(tile, yield_units=yield_units)


def plant_at_end_of_day(plant: PlantTile, day: int) -> PlantTile | WeedTile:
    """Return ``plant`` after the end-of-day refresh closing ``day``.

    A watered plant's unwatered streak resets; otherwise it grows, and
    a streak of 2 turns the plant into a weed. Watered state is cleared.
    A surviving ongoing crop produces on day ``first_yield_day`` of its
    age and every ``interval`` days after, ``max_yield`` times in all,
    whether or not it was watered: 1 unit, or 2 if it was watered and
    fertilized, capped at ``max_yield``. Its last production sets its
    lifespan to end two days later. One-time crops never produce here.
    """
    rules = CROPS[plant.crop]
    was_watered = plant.watered_today
    unwatered = 0 if was_watered else plant.consecutive_unwatered + 1
    if unwatered >= 2:
        return WeedTile()
    plant = replace(plant, watered_today=False, consecutive_unwatered=unwatered)
    if not rules.ongoing:
        return plant

    next_day = day + 1
    days_since_first = next_day - plant.planted_day - rules.first_yield_day
    if days_since_first < 0 or days_since_first % rules.interval != 0:
        return plant
    production = days_since_first // rules.interval + 1
    if production > rules.max_yield:
        return plant
    fertilized = was_watered and plant.fertilized_until_day >= day
    yield_units = min(rules.max_yield, plant.yield_units + (2 if fertilized else 1))
    plant = replace(plant, yield_units=yield_units)
    if production == rules.max_yield:
        plant = replace(plant, max_lifespan_step=(next_day + 1) * TURNS_PER_DAY)
    return plant


def animal_at_end_of_day(animal: AnimalTile, day: int) -> AnimalTile | StructureTile:
    """Return ``animal`` after the end-of-day refresh closing ``day``.

    A fed animal's unfed streak resets; otherwise it grows, and a streak
    of 2 means the animal escapes, leaving its empty structure. On a
    production day (``first_yield_day`` of its age and every
    ``interval`` days after) it gains 1 unit, plus its banked care bonus
    if it was fed, capped at ``max_held``; the bank is cleared either
    way. A day it was fed and cared for banks 1 more. Fertilizer becomes
    available, and fed and cared state are cleared.
    """
    rules = ANIMALS[animal.animal]
    unfed = 0 if animal.fed_today else animal.consecutive_unfed + 1
    if unfed >= 2:
        return StructureTile(structure=rules.structure)

    yield_units = animal.yield_units
    bonus = animal.pending_care_bonus
    days_since_first = day + 1 - animal.placed_day - rules.first_yield_day
    if days_since_first >= 0 and days_since_first % rules.interval == 0:
        paid = bonus if animal.fed_today else 0
        yield_units = min(rules.max_held, yield_units + 1 + paid)
        bonus = 0
    if animal.cared_today and animal.fed_today:
        bonus += 1
    return replace(
        animal,
        consecutive_unfed=unfed,
        yield_units=yield_units,
        pending_care_bonus=bonus,
        fertilizer_available=True,
        fed_today=False,
        cared_today=False,
    )


def _tile_at_end_of_day(tile: TileValue, day: int) -> TileValue:
    if isinstance(tile, PlantTile):
        return plant_at_end_of_day(tile, day)
    if isinstance(tile, AnimalTile):
        return animal_at_end_of_day(tile, day)
    return tile


# --- farms ---------------------------------------------------------------


def changes_after_turn(farm: Farm, step: int) -> bool:
    """Return whether ``farm_after_turn`` can change any tile of ``farm`` at ``step``.

    Only the end-of-day sweep, on the day's last turn, and plant decay
    (``decays_at``) change tiles; on any other turn every tile is returned
    unchanged. Only plants are checked for decay.
    """
    if is_last_turn_of_day(step):
        return True
    for row in farm.tiles:
        for tile in row:
            if isinstance(tile, PlantTile) and decays_at(tile, step):
                return True
    return False


def _is_tuple_grid(tiles: Sequence[Sequence[TileValue]]) -> bool:
    """Return whether ``tiles`` is already a tuple of tuples."""
    if not isinstance(tiles, tuple):
        return False
    for row in tiles:
        if not isinstance(row, tuple):
            return False
    return True


def farm_after_turn(farm: Farm, step: int) -> Farm:
    """Return ``farm`` after the end-of-turn effects of the turn at ``step``.

    Plants decay; on the last turn of the day, every plant and animal
    is refreshed, the farmer returns to the spawn tile, hands are
    dismissed, and ``hires_today`` resets. The tile grid is returned as
    a tuple of tuples.

    Those are the only changes, so when ``changes_after_turn`` is false
    the farm is returned as it is, once its grid is a tuple of tuples:
    the result is exactly equal to rebuilding it, without visiting every
    tile again.
    """
    if not changes_after_turn(farm, step):
        if _is_tuple_grid(farm.tiles):
            return farm
        return replace(farm, tiles=tuple(tuple(row) for row in farm.tiles))
    tiles = tuple(tuple(decayed_tile(tile, step) for tile in row) for row in farm.tiles)
    if not is_last_turn_of_day(step):
        return replace(farm, tiles=tiles)
    day = step // TURNS_PER_DAY
    tiles = tuple(tuple(_tile_at_end_of_day(tile, day) for tile in row) for row in tiles)
    return replace(
        farm,
        tiles=tiles,
        farmer=spawn_position(farm),
        hands=[],
        hires_today=0,
    )
