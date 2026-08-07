"""Translates raw Kaggle observations into Dimitri's internal models.

The Parser is the boundary between the Kaggle environment's raw
observation dictionary and Dimitri's internal, immutable data models
(GameState, Player, Inventory, Market). Everything on the Kaggle side
of that boundary is untyped, nested dictionaries and lists; everything
on Dimitri's side is structured, typed, immutable data.

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

from dimitri.models.game_state import GameState
from dimitri.models.inventory import Inventory
from dimitri.models.market import Market
from dimitri.models.player import Player


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
    day = _parse_day(observation)
    inventory = _parse_inventory(observation)
    player = _parse_player(observation, inventory)
    market = _parse_market(observation)

    return GameState(
        day=day,
        player=player,
        market=market,
        raw_observation=observation,
    )


def _parse_day(observation: dict) -> int:
    """Extract the current in-game day from the observation."""
    return _get(observation, "day", context="observation")


def _parse_player(observation: dict, inventory: Inventory) -> Player:
    """Construct Dimitri's Player from the observation.

    Args:
        observation: The raw observation dictionary.
        inventory: Dimitri's already-parsed Inventory, reused here so
            that Player and GameState refer to the same inventory
            snapshot rather than parsing it twice.
    """
    player_id = _get(observation, "player", context="observation")
    farms = _get(observation, "farms", context="observation")

    try:
        farm = farms[player_id]
    except (IndexError, TypeError) as exc:
        raise ParseError(
            f"No entry for player {player_id!r} in observation['farms']"
        ) from exc

    money = _get(farm, "money", context=f"observation['farms'][{player_id!r}]")

    return Player(player_id=player_id, money=int(money), inventory=inventory)


def _parse_inventory(observation: dict) -> Inventory:
    """Construct Dimitri's Inventory from the observation's shed contents."""
    private = _get(observation, "private", context="observation")
    shed = _get(private, "shed", context="observation['private']")
    return Inventory(items=dict(shed))


def _parse_market(observation: dict) -> Market:
    """Construct the shared Market from the observation's price data."""
    market = _get(observation, "market", context="observation")
    prices = _get(market, "prices", context="observation['market']")
    return Market(prices=dict(prices))


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
