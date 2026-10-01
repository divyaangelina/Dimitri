"""Represents a single candidate game action considered by the Planner.

An Action describes one possible move Dimitri could make — what kind of
action it is, what it targets, and how many units it involves. It is a
representation only: it carries no execution logic, no validation
against game rules, and no judgement about whether it is a good idea.
Choosing among actions belongs to the Executive downstream.

Action types use the Kaggriculture API's own names. The API submits
farmer, hand, and market actions separately::

    {"farmer": [...], "hands": [...], "market": [...]}

Market actions are listed in ``MARKET_ACTION_TYPES``. Farm work such as
PLANT, WATER, HARVEST, and DROP, and movement (``MOVEMENT_ACTION_TYPES``),
is carried out by the farmer or a hand, never through the market.
Movement, WATER, HARVEST, and DROP carry no target: ``Action(NORTH)``,
``Action(WATER)``.
Routing each action to its submission channel belongs to the Operator.
"""

from dataclasses import dataclass

# Farm work, performed by the farmer or a hand.
PLANT = "PLANT"
WATER = "WATER"
HARVEST = "HARVEST"
DROP = "DROP"

# Movement, performed by the farmer or a hand. One step in that direction.
NORTH = "NORTH"
SOUTH = "SOUTH"
EAST = "EAST"
WEST = "WEST"

MOVEMENT_ACTION_TYPES = frozenset({NORTH, SOUTH, EAST, WEST})

# Market actions, as named by the Kaggriculture API.
BUY_SEED = "BUY_SEED"
BUY_ANIMAL = "BUY_ANIMAL"
BUY_PRODUCT = "BUY_PRODUCT"
SELL = "SELL"
HIRE = "HIRE"
BUY_LAND = "BUY_LAND"

MARKET_ACTION_TYPES = frozenset(
    {BUY_SEED, BUY_ANIMAL, BUY_PRODUCT, SELL, HIRE, BUY_LAND}
)


@dataclass(frozen=True)
class Action:
    """An immutable description of one possible game action.

    Attributes:
        action_type: The kind of action, using the Kaggriculture API
            name (e.g. "BUY_PRODUCT", "SELL", "PLANT").
        target: The resource or crop the action applies to, if any.
            Movement actions have no target.
        quantity: The number of units the action involves.
    """

    action_type: str
    target: str | None = None
    quantity: int = 1
