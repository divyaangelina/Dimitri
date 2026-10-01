"""Represents a proposed sequence of turns for pursuing an Opportunity.

A Plan answers "what sequence of actions would pursue this
opportunity?". It sits between Opportunity and Action in Dimitri's
planning hierarchy:

    Opportunity  what could we pursue?
        -> Plan  what sequence of actions would pursue it?
        -> Action  what do we execute right now?

A Plan is a hypothesis, not a commitment. Nothing obliges Dimitri to
carry out the rest of a plan after its first turn: each turn Dimitri
observes the actual GameState again and can re-evaluate, revise, or
abandon any plan in light of it.

Its steps are the existing executable Turns, so there is one action
representation throughout. ``turns[i]`` is the Turn intended for the
``i``-th game turn from the plan's start; waiting is an explicit idle
``Turn()``. A plan need not be executable today: its later turns may
depend on state (seeds held, a ripe plant) that does not exist yet.

The horizon is how many game turns the plan spans. It is declared, not
calculated: this module never works out crop timing, profit, or any
other value, and a Plan carries no score or evaluation. Game turns in
the horizon beyond the listed turns have no intended actions.
"""

from dataclasses import dataclass

from dimitri.analyst.opportunity import Opportunity
from dimitri.planner.action import Action
from dimitri.planner.turn import Turn


@dataclass(frozen=True)
class Plan:
    """An immutable hypothesis for pursuing one Opportunity.

    Attributes:
        opportunity: The Opportunity this plan pursues.
        turns: The intended Turn for each game turn from the plan's
            start, in order. A list is accepted and stored as a tuple.
            Empty when the plan intends no actions (e.g. holding cash).
        horizon: The number of game turns the plan spans. At least
            ``len(turns)``.
        label: A short human-readable name for the plan, e.g.
            ``"tomato on (4, 4)"``. Descriptive only; plans are
            compared and hashed by value.
    """

    opportunity: Opportunity
    turns: tuple[Turn, ...]
    horizon: int
    label: str = ""

    def __post_init__(self) -> None:
        """Store ``turns`` as a tuple and reject malformed fields.

        Raises:
            TypeError: If a field has the wrong type.
            ValueError: If ``horizon`` is negative or shorter than the
                listed turns.
        """
        if not isinstance(self.opportunity, Opportunity):
            raise TypeError(
                f"Plan.opportunity must be an Opportunity, "
                f"got {type(self.opportunity).__name__}"
            )
        if not isinstance(self.turns, (tuple, list)):
            raise TypeError(
                f"Plan.turns must be a tuple of Turn, got {type(self.turns).__name__}"
            )
        for index, turn in enumerate(self.turns):
            if not isinstance(turn, Turn):
                raise TypeError(
                    f"Plan.turns[{index}] must be a Turn, got {type(turn).__name__}"
                )
        object.__setattr__(self, "turns", tuple(self.turns))
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int):
            raise TypeError(
                f"Plan.horizon must be an int, got {type(self.horizon).__name__}"
            )
        if self.horizon < len(self.turns):
            raise ValueError(
                f"Plan.horizon ({self.horizon}) must cover its "
                f"{len(self.turns)} turns"
            )
        if not isinstance(self.label, str):
            raise TypeError(
                f"Plan.label must be a str, got {type(self.label).__name__}"
            )

    def actions(self) -> tuple[Action, ...]:
        """Return every intended action, in the order it would be applied.

        Turns are taken in plan order, and each turn's actions in the
        order Kaggriculture applies them. Idle turns contribute nothing.
        """
        return tuple(action for turn in self.turns for action in turn.actions())
