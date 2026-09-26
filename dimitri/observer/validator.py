"""Verifies that a parsed GameState is structurally complete.

The Validator is the last checkpoint between the Observer and the rest
of Dimitri's pipeline. Once the Parser has translated a raw Kaggle
observation into a GameState, the Validator confirms that the result
is structurally sound — the right models are present, and their
fields hold values of the expected shape and type — before any other
module is allowed to depend on it.

The Validator checks structure only. It does not evaluate game logic,
enforce strategy, calculate values, or make decisions of any kind, and
it never corrects or guesses at data on the caller's behalf. A
GameState that fails validation indicates a problem upstream (in the
Parser or in the raw observation itself), and the Validator's job is
only to surface that problem clearly, not to work around it.

The Validator has no side effects: it never mutates the GameState it
is given, and it returns nothing on success. Its only externally
visible behavior is raising ValidationError when something is wrong.
"""

from collections.abc import Mapping

from dimitri.models.game_state import GameState
from dimitri.models.inventory import Inventory
from dimitri.models.market import Market
from dimitri.models.player import Player


class ValidationError(Exception):
    """Raised when a GameState is not structurally complete.

    This is the only kind of failure the Validator produces. It never
    attempts to repair or complete a malformed GameState — it only
    reports, clearly, what was expected and where.
    """


def validate(game_state: GameState) -> None:
    """Verify that a GameState is structurally complete.

    This is the Validator's sole public entry point. It checks that
    the required models are present on ``game_state`` and that their
    fields hold values of the expected type and shape. No game logic,
    strategy, or business rule is evaluated here — this function only
    confirms that the data is safe for the rest of Dimitri's pipeline
    to consume.

    ``game_state`` is never modified by this function.

    Args:
        game_state: The GameState to check, typically produced by
            dimitri.observer.parser.parse.

    Returns:
        None. A successful validation is indicated by returning
        normally.

    Raises:
        ValidationError: If ``game_state``, or any of the models it is
            composed of, is missing a required field or holds a value
            of an unexpected type.
    """
    if not isinstance(game_state, GameState):
        raise ValidationError(
            f"Expected a GameState, got {type(game_state).__name__}"
        )

    if not isinstance(game_state.day, int):
        raise ValidationError(
            f"GameState.day must be an int, got {type(game_state.day).__name__}"
        )

    if not isinstance(game_state.raw_observation, dict):
        raise ValidationError(
            "GameState.raw_observation must be a dict, got "
            f"{type(game_state.raw_observation).__name__}"
        )

    _validate_player(game_state.player)
    _validate_market(game_state.market)


def _validate_player(player: Player) -> None:
    """Verify that a Player is structurally complete."""
    if not isinstance(player, Player):
        raise ValidationError(
            f"GameState.player must be a Player, got {type(player).__name__}"
        )

    if not isinstance(player.player_id, int):
        raise ValidationError(
            "Player.player_id must be an int, got "
            f"{type(player.player_id).__name__}"
        )

    if not isinstance(player.money, int):
        raise ValidationError(
            f"Player.money must be an int, got {type(player.money).__name__}"
        )

    _validate_inventory(player.inventory, context="Player.inventory")


def _validate_market(market: Market) -> None:
    """Verify that a Market is structurally complete."""
    if not isinstance(market, Market):
        raise ValidationError(
            f"GameState.market must be a Market, got {type(market).__name__}"
        )

    _validate_str_to_int_mapping(market.prices, context="Market.prices")


def _validate_inventory(inventory: Inventory, *, context: str) -> None:
    """Verify that an Inventory is structurally complete.

    Args:
        inventory: The Inventory to check.
        context: A human-readable description of where ``inventory``
            came from, used to make error messages specific (e.g.
            "Player.inventory" vs. "GameState.inventory").
    """
    if not isinstance(inventory, Inventory):
        raise ValidationError(
            f"{context} must be an Inventory, got {type(inventory).__name__}"
        )

    _validate_str_to_int_mapping(inventory.items, context=f"{context}.items")


def _validate_str_to_int_mapping(value: object, *, context: str) -> None:
    """Verify that a value is a Mapping[str, int].

    Args:
        value: The value to check.
        context: A human-readable description of where ``value`` came
            from, used to make error messages specific.
    """
    if not isinstance(value, Mapping):
        raise ValidationError(
            f"{context} must be a mapping, got {type(value).__name__}"
        )

    for key, item_value in value.items():
        if not isinstance(key, str):
            raise ValidationError(
                f"{context} must have str keys, got key {key!r} of type "
                f"{type(key).__name__}"
            )
        if not isinstance(item_value, int):
            raise ValidationError(
                f"{context}[{key!r}] must be an int, got "
                f"{type(item_value).__name__}"
            )
