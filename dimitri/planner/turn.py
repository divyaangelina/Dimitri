"""Represents one complete Kaggriculture turn.

A Kaggriculture turn is submitted as three channels at once: one action
for the main farmer, one action per hired hand, and an ordered list of
market orders. A Turn mirrors that structure using the Planner's
existing Action for every entry, so there is exactly one action
representation across the three channels.

A hand with nothing to do this turn is written as None in ``hands``,
the same way a passing farmer is None. Hands are positional — entry
``i`` belongs to the farm's ``i``-th hand — so None keeps each later
hand's action aligned with its hand: ``hands=(None, Action(NORTH))``
means hand 1 passes while hand 2 moves north.

A Turn is a representation only: it carries no execution logic, no
validation against game rules, and no judgement about whether it is a
good idea. Writing it in the Kaggriculture API format belongs to the
Operator downstream.
"""

from dataclasses import dataclass

from dimitri.planner.action import MARKET_ACTION_TYPES, Action


@dataclass(frozen=True)
class Turn:
    """An immutable description of every action taken in one turn.

    Attributes:
        farmer: The main farmer's action, or None when the farmer
            passes.
        hands: One entry per hired hand, in the farm's hands order:
            that hand's action, or None when it passes. Empty when no
            hand acts. A list is accepted and stored as a tuple.
        market: Market orders, in submission order. Empty when no
            order is placed.
    """

    farmer: Action | None = None
    hands: tuple[Action | None, ...] = ()
    market: tuple[Action, ...] = ()

    def __post_init__(self) -> None:
        """Store ``hands`` as a tuple and reject malformed hand entries.

        Raises:
            TypeError: If ``hands`` is not a tuple or list, or any entry
                is neither an Action nor None.
        """
        if not isinstance(self.hands, (tuple, list)):
            raise TypeError(
                f"Turn.hands must be a tuple of Action or None, "
                f"got {type(self.hands).__name__}"
            )
        for index, hand in enumerate(self.hands):
            if hand is not None and not isinstance(hand, Action):
                raise TypeError(
                    f"Turn.hands[{index}] must be an Action or None, "
                    f"got {type(hand).__name__}"
                )
        object.__setattr__(self, "hands", tuple(self.hands))

    @classmethod
    def from_action(cls, action: Action) -> "Turn":
        """Return a Turn containing only ``action``, in its own channel.

        Market actions become the turn's single market order and the
        farmer passes; farm work is performed by the farmer.
        """
        if action.action_type in MARKET_ACTION_TYPES:
            return cls(market=(action,))
        return cls(farmer=action)

    def actions(self) -> tuple[Action, ...]:
        """Return every action in the order Kaggriculture applies them.

        The environment applies the farmer's action, then each hand's
        action in order, then the market orders. Passing units (None)
        contribute no action.
        """
        farmer = () if self.farmer is None else (self.farmer,)
        hands = tuple(hand for hand in self.hands if hand is not None)
        return (*farmer, *hands, *self.market)
