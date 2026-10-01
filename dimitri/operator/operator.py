"""Translates the Executive's Decision into the Kaggriculture action dict.

Operator answers one question: how is a decided Turn written in the
Kaggriculture API's own format? ``execute`` accepts only a Decision from
the Executive, never candidates or a PlanningResult. The API submits one
turn's actions as::

    {
        "farmer": [op, ...args],          # one main-farmer op
        "hands":  [[op, ...args], ...],   # one op per hired hand, in order
        "market": [[op, ...args], ...],   # ordered market orders
    }

Farm work (PLANT, WATER, HARVEST, DROP) and movement (NORTH, SOUTH,
EAST, WEST) are written for the farmer or a hand: PLANT carries its
crop, and every other unit op is the op alone, e.g. ["NORTH"] or
["WATER"]. Market actions
are written as market orders: BUY_SEED, BUY_ANIMAL, BUY_PRODUCT, and
SELL carry a target and quantity; HIRE and BUY_LAND take no arguments.
A farmer or hand with nothing to do (None) is sent PASS. The API reads
hand ops by position, so a passing hand keeps its ["PASS"] slot and
every later hand's op stays aligned with its hand.

It never chooses, ranks, or scores actions, never simulates outcomes,
and never reads or modifies any GameState. Actions that cannot be
written in the API format raise ValueError rather than being silently
dropped.
"""

from collections.abc import Sequence

from dimitri.executive.decision import Decision
from dimitri.planner.action import (
    BUY_ANIMAL,
    BUY_LAND,
    BUY_PRODUCT,
    BUY_SEED,
    DROP,
    HARVEST,
    HIRE,
    MOVEMENT_ACTION_TYPES,
    PLANT,
    SELL,
    WATER,
    Action,
)

PASS = "PASS"

# Unit ops written as [op] alone, with no arguments.
_BARE_UNIT_TYPES = frozenset({WATER, HARVEST, DROP}) | MOVEMENT_ACTION_TYPES

# Farm work the Operator can write for the farmer or a hand.
UNIT_ACTION_TYPES = frozenset({PLANT}) | _BARE_UNIT_TYPES

# Market actions written as [op, target, quantity].
_TARGETED_MARKET_TYPES = frozenset({BUY_SEED, BUY_ANIMAL, BUY_PRODUCT, SELL})

# Market actions written as [op] alone.
_ATOMIC_MARKET_TYPES = frozenset({HIRE, BUY_LAND})


class Operator:
    """Writes decided Turns in the Kaggriculture API's action format."""

    def execute(self, decision: Decision) -> dict:
        """Return the complete API action dict for the Executive's Decision.

        Each channel of the decided Turn is written to the matching API
        key: the farmer's action (or PASS), one op per hand, and the
        market orders in order.

        Raises:
            TypeError: If ``decision`` is not a Decision.
            ValueError: If any action in the decided turn cannot be
                written for its channel.
        """
        if not isinstance(decision, Decision):
            raise TypeError(
                f"Operator executes only a Decision, got {type(decision).__name__}"
            )
        turn = decision.turn
        return self.compose(farmer=turn.farmer, hands=turn.hands, market=turn.market)

    def compose(
        self,
        farmer: Action | None = None,
        hands: Sequence[Action | None] = (),
        market: Sequence[Action] = (),
    ) -> dict:
        """Return the complete API action dict for one turn.

        Args:
            farmer: The main farmer's action, or None to PASS.
            hands: One action per hired hand, in the farm's hands order,
                or None for a hand that PASSes.
            market: Market orders, in submission order.

        Raises:
            ValueError: If any action cannot be written for its channel.
        """
        return {
            "farmer": self._unit_op_or_pass(farmer),
            "hands": [self._unit_op_or_pass(action) for action in hands],
            "market": [self.to_market_order(action) for action in market],
        }

    @classmethod
    def _unit_op_or_pass(cls, action: Action | None) -> list:
        """Return ``action`` as a farmer or hand op, or ["PASS"] for None."""
        return [PASS] if action is None else cls.to_unit_op(action)

    @staticmethod
    def to_unit_op(action: Action) -> list:
        """Return ``action`` as a farmer or hand op, e.g. ["PLANT", "WHEAT"] or ["WATER"].

        Raises:
            ValueError: If ``action`` is not supported farm work or is
                malformed.
        """
        if action.action_type not in UNIT_ACTION_TYPES:
            raise ValueError(
                f"Unsupported farmer/hand action type: {action.action_type!r}"
            )
        if action.action_type in _BARE_UNIT_TYPES:
            if action.target is not None:
                raise ValueError(f"{action.action_type} takes no target")
            _require_single_unit(action)
            return [action.action_type]
        _require_target(action)
        _require_single_unit(action)
        return [action.action_type, action.target]

    @staticmethod
    def to_market_order(action: Action) -> list:
        """Return ``action`` as a market order, e.g. ["SELL", "WHEAT", 2].

        Raises:
            ValueError: If ``action`` is not a market action or is
                malformed.
        """
        if action.action_type in _TARGETED_MARKET_TYPES:
            _require_target(action)
            _require_positive_quantity(action)
            return [action.action_type, action.target, action.quantity]
        if action.action_type in _ATOMIC_MARKET_TYPES:
            if action.target is not None:
                raise ValueError(f"{action.action_type} takes no target")
            _require_single_unit(action)
            return [action.action_type]
        raise ValueError(f"Unsupported market action type: {action.action_type!r}")


def _require_target(action: Action) -> None:
    if not isinstance(action.target, str) or not action.target:
        raise ValueError(f"{action.action_type} requires a target")


def _require_positive_quantity(action: Action) -> None:
    quantity = action.quantity
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ValueError(
            f"{action.action_type} requires a positive integer quantity, "
            f"got {quantity!r}"
        )


def _require_single_unit(action: Action) -> None:
    if action.quantity != 1 or isinstance(action.quantity, bool):
        raise ValueError(
            f"{action.action_type} is a single-unit action, "
            f"got quantity {action.quantity!r}"
        )
