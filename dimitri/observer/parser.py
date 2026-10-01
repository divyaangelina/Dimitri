"""Translates raw Kaggle observations into Dimitri's internal models.

The Parser is the boundary between the Kaggle environment's raw
observation dictionary and Dimitri's internal, immutable data models
(GameState, Player, Opponent, Farm, Inventory, Market). Everything on
the Kaggle side of that boundary is untyped, nested dictionaries and
lists; everything on Dimitri's side is structured, typed, immutable
data.

The Parser performs translation only. It extracts values from the raw
observation and uses them to construct model objects — nothing more.
It does not validate business rules, guess at missing values, perform
calculations, detect bottlenecks, predict anything, or make decisions.
Those responsibilities belong to the Analyst, Planner, Executive, and
Operator modules downstream, all of which consume a GameState rather
than the raw observation.

If the raw observation is missing a required field or has an
unexpected shape, the Parser raises a ParseError rather than
substituting a default or attempting to repair the input. A malformed
observation is a signal that something upstream is wrong, and it
should fail loudly and specifically rather than propagate silently
into Dimitri's decision-making.
"""

from collections.abc import Mapping
from typing import Any

from dimitri.models.farm import Farm, TileValue
from dimitri.models.game_state import GameState
from dimitri.models.inventory import Inventory
from dimitri.models.market import Market
from dimitri.models.opponent import Opponent
from dimitri.models.player import Player
from dimitri.models.tile import (
    AnimalTile,
    PlantTile,
    StructureTile,
    TileContents,
    WeedTile,
)
from dimitri.models.town import Town

_LOCKED = "LOCKED"
_STRUCTURE_KINDS = ("COOP", "PASTURE")


class ParseError(ValueError):
    """Raised when a raw Kaggle observation is missing or malformed.

    This is intentionally the only kind of failure the Parser produces.
    It never attempts to repair or default a malformed observation —
    it only reports, clearly, what was expected and where.
    """


def parse(observation: dict) -> GameState:
    """Translate a raw Kaggle observation dictionary into a GameState.

    This is the Parser's sole public entry point. It reads the
    observation, extracts the information Dimitri's models require,
    and constructs the corresponding immutable model objects. No
    reasoning, validation of business rules, or decision-making occurs
    here — this function only translates data from one shape into
    another.

    The input dictionary is never modified.

    Args:
        observation: The raw observation dictionary produced by the
            Kaggle environment for the current turn.

    Returns:
        A fully populated, immutable GameState representing the same
        moment described by ``observation``.

    Raises:
        ParseError: If a field required by Dimitri's models is missing
            from ``observation`` or is not shaped as expected.
    """
    step = _parse_step(observation)
    day = _parse_day(observation)
    hour = _parse_hour(observation)
    player = _parse_player(observation)
    opponent = _parse_opponent(observation)
    market = _parse_market(observation)
    town = _parse_town(observation)

    return GameState(
        step=step,
        day=day,
        hour=hour,
        player=player,
        opponent=opponent,
        market=market,
        town=town,
        raw_observation=observation,
    )


def _parse_step(observation: dict) -> int:
    """Extract the current episode turn from the observation."""
    return _typed(observation, "step", int, context="observation")


def _parse_day(observation: dict) -> int:
    """Extract the current in-game day from the observation."""
    return _get(observation, "day", context="observation")


def _parse_hour(observation: dict) -> int:
    """Extract the current turn-within-day from the observation."""
    return _get(observation, "hour", context="observation")


def _parse_player(observation: dict) -> Player:
    """Construct Dimitri's own Player from the observation.

    Combines the public farm dict at ``farms[player_id]`` with the
    private shed and seed data, which are only ever reported for
    Dimitri's own side of the match.
    """
    player_id = _get(observation, "player", context="observation")
    farm_dict = _get_farm_dict(observation, player_id)

    private = _get(observation, "private", context="observation")
    shed = _get(private, "shed", context="observation['private']")
    seeds = _get(private, "seeds", context="observation['private']")
    unit_inventories = _parse_unit_inventories(
        _get(private, "inventories", context="observation['private']"),
        context="observation['private']['inventories']",
    )

    money = _get(farm_dict, "money", context=f"observation['farms'][{player_id!r}]")
    farm = _parse_farm(farm_dict, context=f"observation['farms'][{player_id!r}]")

    return Player(
        player_id=player_id,
        money=int(money),
        inventory=Inventory(items=dict(shed)),
        seeds=dict(seeds),
        farm=farm,
        unit_inventories=unit_inventories,
    )


def _parse_unit_inventories(inventories: Any, *, context: str) -> tuple[Inventory, ...]:
    """Translate ``private.inventories`` into one Inventory per unit.

    Order is preserved exactly: index 0 is the main farmer and the
    rest are hands. Each inventory's items are copied so the result
    shares no mutable state with the observation.
    """
    result = []
    for index, items in enumerate(_as_list(inventories, context=context)):
        if not isinstance(items, Mapping):
            raise ParseError(
                f"Expected a mapping for {context}[{index}], "
                f"got {type(items).__name__}"
            )
        result.append(Inventory(items=dict(items)))
    return tuple(result)


def _parse_opponent(observation: dict) -> Opponent:
    """Construct the Opponent from the observation.

    Only the public farm dict for the opponent's index is available —
    there is no private shed or seed data to parse for the opponent,
    matching what the environment actually discloses.
    """
    player_id = _get(observation, "player", context="observation")
    farms = _get(observation, "farms", context="observation")
    opponent_id = _opponent_id(player_id, farms)
    farm_dict = _get_farm_dict(observation, opponent_id)

    money = _get(farm_dict, "money", context=f"observation['farms'][{opponent_id!r}]")
    farm = _parse_farm(farm_dict, context=f"observation['farms'][{opponent_id!r}]")

    return Opponent(player_id=opponent_id, money=int(money), farm=farm)


def _parse_farm(farm_dict: dict, *, context: str) -> Farm:
    """Construct a Farm from one entry of the observation's ``farms`` list."""
    return Farm(
        tiles=_parse_tiles(
            _get(farm_dict, "tiles", context=context),
            context=f"{context}['tiles']",
        ),
        farmer=_get(farm_dict, "farmer", context=context),
        hands=_get(farm_dict, "hands", context=context),
        unlocked_quadrants=_get(farm_dict, "unlocked_quadrants", context=context),
        hires_today=_get(farm_dict, "hires_today", context=context),
    )


def _parse_tiles(tiles: Any, *, context: str) -> tuple[tuple[TileValue, ...], ...]:
    """Translate the ``tiles[y][x]`` grid into an immutable grid of TileValues.

    The grid's rows and columns are preserved exactly; each tile is
    translated independently by _parse_tile.
    """
    rows = _as_list(tiles, context=context)
    return tuple(
        tuple(
            _parse_tile(tile, context=f"{context}[{y}][{x}]")
            for x, tile in enumerate(_as_list(row, context=f"{context}[{y}]"))
        )
        for y, row in enumerate(rows)
    )


def _parse_tile(tile: Any, *, context: str) -> TileValue:
    """Translate a single raw tile into a TileValue.

    ``None`` and ``"LOCKED"`` are passed through unchanged. A tile dict
    is translated into the model matching its ``kind`` (and, for a
    coop or pasture, whether it carries an ``animal``). Any other
    value, or a dict with an unrecognized ``kind``, raises ParseError
    rather than being passed through opaquely.
    """
    if tile is None or tile == _LOCKED:
        return tile
    if not isinstance(tile, Mapping):
        raise ParseError(
            f"Expected None, {_LOCKED!r}, or a tile mapping for {context}, "
            f"got {tile!r}"
        )
    return _parse_tile_contents(tile, context=context)


def _parse_tile_contents(tile: Mapping[str, Any], *, context: str) -> TileContents:
    """Translate an occupied tile dict into its TileContents model."""
    kind = _get(tile, "kind", context=context)

    if kind == "PLANT":
        return PlantTile(
            crop=_typed(tile, "crop", str, context=context),
            planted_day=_typed(tile, "planted_day", int, context=context),
            watered_today=_typed(tile, "watered_today", bool, context=context),
            consecutive_unwatered=_typed(
                tile, "consecutive_unwatered", int, context=context
            ),
            yield_units=_typed(tile, "yield_units", int, context=context),
            max_lifespan_step=_typed(tile, "max_lifespan_step", int, context=context),
            fertilized_until_day=_typed(
                tile, "fertilized_until_day", int, context=context
            ),
        )

    if kind == "WEED":
        return WeedTile()

    if kind in _STRUCTURE_KINDS:
        if "animal" not in tile:
            return StructureTile(structure=kind)
        return AnimalTile(
            structure=kind,
            animal=_typed(tile, "animal", str, context=context),
            placed_day=_typed(tile, "placed_day", int, context=context),
            yield_units=_typed(tile, "yield_units", int, context=context),
            consecutive_unfed=_typed(tile, "consecutive_unfed", int, context=context),
            fed_today=_typed(tile, "fed_today", bool, context=context),
            cared_today=_typed(tile, "cared_today", bool, context=context),
            fertilizer_available=_typed(
                tile, "fertilizer_available", bool, context=context
            ),
            pending_care_bonus=_typed(tile, "pending_care_bonus", int, context=context),
        )

    raise ParseError(f"Unknown tile kind {kind!r} in {context}")


def _as_list(value: Any, *, context: str) -> list:
    """Require ``value`` to be a list, raising a clear ParseError otherwise."""
    if not isinstance(value, list | tuple):
        raise ParseError(
            f"Expected a sequence for {context}, got {type(value).__name__}"
        )
    return list(value)


def _typed(source: Mapping[str, Any], key: str, expected: type, *, context: str) -> Any:
    """Look up ``key`` in ``source`` and require it to be of type ``expected``.

    ``bool`` is a subclass of ``int`` in Python, so an int field
    explicitly rejects bools (and vice versa) to catch swapped values.
    """
    value = _get(source, key, context=context)
    is_bool = isinstance(value, bool)
    if not isinstance(value, expected) or (expected is int and is_bool):
        raise ParseError(
            f"Expected {expected.__name__} for '{key}' in {context}, "
            f"got {type(value).__name__}"
        )
    return value


def _parse_market(observation: dict) -> Market:
    """Construct the shared Market from the observation's price and supply data."""
    market = _get(observation, "market", context="observation")
    prices = _get(market, "prices", context="observation['market']")
    inventory = _get(market, "inventory", context="observation['market']")
    return Market(prices=dict(prices), inventory=dict(inventory))


def _parse_town(observation: dict) -> Town:
    """Construct the shared Town from the observation's ``town`` dict."""
    town = _get(observation, "town", context="observation")
    context = "observation['town']"
    shops = _as_list(
        _get(town, "unlocked_shops", context=context),
        context=f"{context}['unlocked_shops']",
    )
    for index, shop in enumerate(shops):
        if not isinstance(shop, str):
            raise ParseError(
                f"Expected str for {context}['unlocked_shops'][{index}], "
                f"got {type(shop).__name__}"
            )
    return Town(unlocked_shops=tuple(shops))


def _get_farm_dict(observation: dict, player_id: Any) -> dict:
    """Look up a single farm dict from the observation's ``farms`` list."""
    farms = _get(observation, "farms", context="observation")
    try:
        return farms[player_id]
    except (IndexError, TypeError) as exc:
        raise ParseError(
            f"No entry for player {player_id!r} in observation['farms']"
        ) from exc


def _opponent_id(player_id: Any, farms: Any) -> int:
    """Determine the opponent's index from the observation's ``farms`` list.

    Rather than assuming a fixed index (e.g. ``1 - player_id``), this
    finds the one other index present in ``farms``, so it holds
    regardless of whether Dimitri is player 0 or player 1.
    """
    try:
        other_indices = [i for i in range(len(farms)) if i != player_id]
    except TypeError as exc:
        raise ParseError(
            f"Expected a sequence for observation['farms'], got {type(farms).__name__}"
        ) from exc

    if len(other_indices) != 1:
        raise ParseError(
            f"Expected exactly one opponent in observation['farms'] besides "
            f"player {player_id!r}, found indices {other_indices!r}"
        )

    return other_indices[0]


def _get(source: Mapping[str, Any], key: str, *, context: str) -> Any:
    """Look up ``key`` in ``source``, raising a clear ParseError if absent.

    This is the Parser's single point of failure handling: every field
    extraction goes through here so that a missing or malformed field
    produces a specific, descriptive error rather than a generic
    KeyError or a silently substituted default.

    Args:
        source: The mapping to look up ``key`` in.
        key: The field name expected to be present in ``source``.
        context: A human-readable description of where ``source`` came
            from, used to make the resulting error message specific.

    Returns:
        The value stored at ``key`` in ``source``.

    Raises:
        ParseError: If ``key`` is missing from ``source``, or if
            ``source`` is not a mapping at all.
    """
    try:
        return source[key]
    except KeyError as exc:
        raise ParseError(f"Missing '{key}' in {context}") from exc
    except TypeError as exc:
        raise ParseError(
            f"Expected a mapping for {context}, got {type(source).__name__}"
        ) from exc
