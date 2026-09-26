"""Orchestrates turning a raw Kaggle observation into a trusted GameState.

The Observer sits at the front of Dimitri's pipeline, between the raw
observation the Kaggle environment hands to the agent each turn and
the rest of Dimitri's modules (Analyst, Planner, Executive, Operator).
It does not parse or validate data itself; it delegates each step to
the existing Parser and Validator and simply orchestrates the two in
sequence:

    raw observation -> parser.parse() -> GameState
                     -> validator.validate() -> trusted GameState

The Observer performs no analysis, calculation, or decision-making of
any kind. Its only job is to produce a GameState that downstream
modules can trust without re-checking it themselves.
"""

from dimitri.models.game_state import GameState
from dimitri.observer.parser import parse
from dimitri.observer.validator import validate


class Observer:
    """Orchestrates parsing and validation of a raw Kaggle observation.

    Observer does not implement parsing or validation logic itself —
    it delegates to dimitri.observer.parser.parse and
    dimitri.observer.validator.validate, and returns the GameState
    those produce. It performs no analysis, strategy evaluation, or
    decision-making, and it holds no history or cached state between
    calls.
    """

    def observe(self, observation: dict) -> GameState:
        """Turn a raw Kaggle observation into a validated GameState.

        The raw observation is parsed into a GameState via
        dimitri.observer.parser.parse, and that GameState is then
        checked via dimitri.observer.validator.validate. Neither the
        observation nor the resulting GameState is modified by this
        method.

        Args:
            observation: The raw observation dictionary produced by
                the Kaggle environment for the current turn.

        Returns:
            The parsed GameState, guaranteed to have already passed
            validation.

        Raises:
            ParseError: If the Parser cannot construct a GameState
                from ``observation``. Propagated unchanged from
                dimitri.observer.parser.parse.
            ValidationError: If the parsed GameState is not
                structurally complete. Propagated unchanged from
                dimitri.observer.validator.validate.
        """
        game_state = parse(observation)
        validate(game_state)
        return game_state
