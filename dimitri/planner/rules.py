"""Kaggriculture's rules for the actions the Simulator supports.

These functions state facts about how the environment applies an
action. For farm work, they cover where a unit stands, what occupies
the tile under it and what it carries, whether PLANT, WATER, HARVEST,
or DROP would take effect, and what each leaves behind. For movement,
they cover where a unit would end up. For the market, they cover the
price the environment quotes for one unit. They mirror
``_apply_unit_action``, ``_new_plant``, ``_is_shed_adjacent``,
``market_price``, and the quotes in ``_process_market`` in the installed
Kaggriculture environment.

Every farm-work op is ignored by the environment when the acting unit
stands on a LOCKED tile, DROP included.

They make no judgement about whether an action is a good idea. The
CandidateGenerator uses them to avoid proposing actions the environment
would ignore, and the Simulator uses them to apply those actions.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace

from dimitri.models.farm import Farm, TileValue
from dimitri.models.game_state import GameState
from dimitri.models.player import Player
from dimitri.models.tile import PlantTile
from dimitri.planner.action import EAST, NORTH, SOUTH, WEST
from dimitri.utils.constants import (
    CROPS,
    MARKET_PARAMS,
    PRICE_FLOOR,
    TURNS_PER_DAY,
)

FARMER = 0
"""Unit index of the main farmer. Hand ``i`` (0-indexed) is unit ``i + 1``."""

MOVES = {
    NORTH: (0, -1),
    SOUTH: (0, 1),
    EAST: (1, 0),
    WEST: (-1, 0),
}
"""The ``(dx, dy)`` step of each movement action. ``y`` grows downward (south)."""


def unit_position(farm: Farm, unit: int) -> Sequence[int] | None:
    """Return the ``[x, y]`` position of ``unit``, or None if it does not exist."""
    if unit == FARMER:
        return farm.farmer
    if 1 <= unit <= len(farm.hands):
        return farm.hands[unit - 1]
    return None


def tile_under(farm: Farm, unit: int) -> TileValue:
    """Return the tile ``unit`` is standing on.

    Raises:
        ValueError: If ``unit`` does not exist or stands off the board.
    """
    position = unit_position(farm, unit)
    if position is None:
        raise ValueError(f"Unit {unit} does not exist on the farm")
    x, y = position
    if not (0 <= y < len(farm.tiles) and 0 <= x < len(farm.tiles[y])):
        raise ValueError(f"Unit {unit} position {list(position)!r} is off the board")
    return farm.tiles[y][x]


def move_destination(farm: Farm, unit: int, direction: str) -> tuple[int, int]:
    """Return where ``unit`` would stand after moving one step in ``direction``.

    The farmer and hands move by the same rule. Any in-bounds tile is a
    valid destination, including LOCKED tiles, occupied tiles, and tiles
    where another unit stands. The environment treats a move off the
    board as a no-op.

    Raises:
        ValueError: If ``direction`` is not a movement action, ``unit``
            does not exist, or the move would leave the board (the
            environment would ignore it).
    """
    if direction not in MOVES:
        raise ValueError(f"Unknown direction: {direction!r}")
    position = unit_position(farm, unit)
    if position is None:
        raise ValueError(f"Unit {unit} does not exist on the farm")
    dx, dy = MOVES[direction]
    x, y = position[0] + dx, position[1] + dy
    if not (0 <= y < len(farm.tiles) and 0 <= x < len(farm.tiles[y])):
        raise ValueError(
            f"Unit {unit} at {list(position)!r} cannot move {direction}: off the board"
        )
    return x, y


def plant_blocker(game_state: GameState, crop: str | None, unit: int) -> str | None:
    """Return why PLANT ``crop`` by ``unit`` would not take effect, or None.

    The environment plants only when the crop is a known crop, the tile
    under the unit is empty and unlocked (``None``), and at least one
    seed of that crop is held.
    """
    if crop not in CROPS:
        return f"Unknown crop: {crop!r}"
    try:
        tile = tile_under(game_state.player.farm, unit)
    except ValueError as exc:
        return str(exc)
    if tile is not None:
        return f"Cannot plant on a non-empty tile: {tile!r}"
    if game_state.player.seeds.get(crop, 0) <= 0:
        return f"No {crop!r} seeds to plant"
    return None


def new_plant(crop: str, day: int) -> PlantTile:
    """Return the PlantTile the environment creates when ``crop`` is planted on ``day``."""
    rules = CROPS[crop]
    return PlantTile(
        crop=crop,
        planted_day=day,
        watered_today=False,
        consecutive_unwatered=1,
        yield_units=0 if rules.ongoing else 1,
        max_lifespan_step=(
            -1 if rules.ongoing else (day + rules.max_yield_day + 1) * TURNS_PER_DAY
        ),
        fertilized_until_day=-1,
    )


def carried_items(player: Player, unit: int) -> Mapping[str, int]:
    """Return what ``unit`` is carrying; a unit with no inventory entry carries nothing."""
    if unit < len(player.unit_inventories):
        return player.unit_inventories[unit].items
    return {}


def is_shed_adjacent(farm: Farm, position: Sequence[int]) -> bool:
    """Return whether ``position`` is one of the four shed-access tiles.

    The shed sits at the board's centre; the access tiles are the four
    tiles around it, one in each quadrant.
    """
    half = len(farm.tiles) // 2
    access = {(half - 1, half - 1), (half, half - 1), (half - 1, half), (half, half)}
    return tuple(position) in access


def water_blocker(game_state: GameState, unit: int) -> str | None:
    """Return why WATER by ``unit`` would not take effect, or None.

    The environment waters only a plant under the unit that has not
    already been watered today.
    """
    try:
        tile = tile_under(game_state.player.farm, unit)
    except ValueError as exc:
        return str(exc)
    if not isinstance(tile, PlantTile):
        return f"Cannot water a tile without a plant: {tile!r}"
    if tile.watered_today:
        return "The plant has already been watered today"
    return None


def watered_plant(plant: PlantTile, day: int) -> PlantTile:
    """Return ``plant`` after the environment waters it on ``day``.

    Watering a one-time crop inside its bonus window, from day
    ``(max_yield_day + 1) // 2`` to ``max_yield_day`` of its age, adds
    one yield unit, or two while fertilized, capped at ``max_yield``.
    Ongoing crops gain no yield from watering itself.
    """
    rules = CROPS[plant.crop]
    yield_units = plant.yield_units
    if not rules.ongoing:
        age = day - plant.planted_day
        if (rules.max_yield_day + 1) // 2 <= age <= rules.max_yield_day:
            bonus = 2 if plant.fertilized_until_day >= day else 1
            yield_units = min(rules.max_yield, yield_units + bonus)
    return replace(plant, watered_today=True, yield_units=yield_units)


def harvest_blocker(game_state: GameState, unit: int) -> str | None:
    """Return why HARVEST of a plant by ``unit`` would not take effect, or None.

    The environment harvests a plant under the unit that holds yield and
    is at least ``first_yield_day`` days old. Animal tiles are also
    harvestable in the environment but are not modelled here.
    """
    try:
        tile = tile_under(game_state.player.farm, unit)
    except ValueError as exc:
        return str(exc)
    if not isinstance(tile, PlantTile):
        return f"Cannot harvest a tile without a plant: {tile!r}"
    if tile.yield_units <= 0:
        return "The plant has no yield to harvest"
    first_yield_day = CROPS[tile.crop].first_yield_day
    if game_state.day - tile.planted_day < first_yield_day:
        return f"{tile.crop} cannot be harvested before day {first_yield_day} of its age"
    return None


def harvested_tile(plant: PlantTile) -> PlantTile | None:
    """Return what the environment leaves on the tile after harvesting ``plant``.

    A one-time crop is removed, leaving an empty tile; an ongoing crop
    stays with no yield.
    """
    if CROPS[plant.crop].ongoing:
        return replace(plant, yield_units=0)
    return None


def drop_blocker(game_state: GameState, unit: int) -> str | None:
    """Return why DROP by ``unit`` would not take effect, or None.

    The environment drops only when the unit stands on an unlocked
    shed-access tile carrying something.
    """
    try:
        tile = tile_under(game_state.player.farm, unit)
    except ValueError as exc:
        return str(exc)
    if tile == "LOCKED":
        return "Cannot act on a LOCKED tile"
    farm = game_state.player.farm
    if not is_shed_adjacent(farm, unit_position(farm, unit)):
        return f"Unit {unit} is not next to the shed"
    if not any(n > 0 for n in carried_items(game_state.player, unit).values()):
        return f"Unit {unit} is carrying nothing to drop"
    return None


def shed_after_drop(
    carried: Mapping[str, int], shed: Mapping[str, int], capacity: int
) -> dict[str, int]:
    """Return the shed after the environment drops ``carried`` into it.

    Items are moved in carried order while the shed has room. Whatever
    does not fit is discarded: the environment empties the unit's
    inventory either way.
    """
    shed = dict(shed)
    for item, quantity in carried.items():
        if quantity <= 0:
            continue
        room = max(0, capacity - sum(shed.values()))
        take = min(quantity, room)
        if take > 0:
            shed[item] = shed.get(item, 0) + take
    return shed


def market_price(item: str, inventory: int) -> int:
    """Return the environment's price for ``item`` at a market ``inventory``.

    Below the reference inventory ``I0`` the price rises (scarcity), and
    above it the price falls (glut), following the item's price curve.
    It is rounded exactly as the environment rounds it and floored at
    PRICE_FLOOR.
    """
    curve = MARKET_PARAMS[item]
    if inventory < curve.I0:
        amp = curve.below_target * curve.base / _shape(curve.below_func, curve.T)
        price = curve.base + amp * _shape(curve.below_func, curve.I0 - inventory)
    else:
        amp = curve.above_target * curve.base / _shape(curve.above_func, curve.T)
        price = curve.base - amp * _shape(curve.above_func, inventory - curve.I0)
    return max(PRICE_FLOOR, int(round(price)))


def sell_quote(item: str, inventory: int) -> int:
    """Return the price paid for selling one unit into a market holding ``inventory``."""
    return market_price(item, inventory)


def buy_quote(item: str, inventory: int) -> int:
    """Return the price charged for buying one unit from a market holding ``inventory``.

    The environment quotes a purchase at the post-buy inventory, so a buy
    followed by a sell against an unchanged market nets zero.
    """
    return market_price(item, inventory - 1)


def _shape(func: str, x: float) -> float:
    x = max(0.0, x)
    if func == "linear":
        return x
    if func == "sq":
        return x * x
    if func == "sqrt":
        return math.sqrt(x)
    if func == "log":
        return math.log(1.0 + x)
    if func == "log10":
        return math.log10(1.0 + x)
    return x
