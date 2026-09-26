"""Represents the shared marketplace visible to all players.

Market models the current state of the economy exactly as observed
from the Kaggle environment: what each resource currently sells for,
and how much of it the market currently holds. It is composed into
GameState alongside Player and Opponent, providing Dimitri's factual
view of the economy.

Prices and inventory are each represented as a mapping rather than
individual fields (e.g. ``wheat_price: int``, ``wheat_inventory: int``)
for the same reason Inventory stores its items as a mapping: the set
of tradable resources is defined by the game, not by Dimitri's
architecture. If a new resource is introduced, it simply becomes a new
key in each mapping — no new field, no new dataclass, no migration.

Like the other models in this package, Market stores facts only. It
never predicts future prices, detects trends, recommends buying or
selling, ranks investments, or estimates future profit. Those
responsibilities belong to the Analyst downstream. Market exists
purely to be read.

Because it is a frozen dataclass, a Market instance cannot be mutated
after construction. Each new observation produces a new Market rather
than modifying an existing one.
"""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Market:
    """An immutable snapshot of the current market economy.

    Market is a pure data container. It represents the economy as it
    currently stands — not economic reasoning about it. All price
    interpretation, trend detection, and buy/sell recommendations
    belong to the Analyst and remain fully independent of this model.

    Market mirrors the design of Inventory by design: both represent
    dynamic collections of game resources keyed by resource name. This
    symmetry keeps Dimitri's API predictable and easy to learn across
    models.

    Attributes:
        prices: A mapping of resource name (e.g. "WHEAT", "EGG",
            "FERTILIZER") to its current market price. Resources not
            present in the mapping should be treated as unpriced by
            callers, typically via ``prices.get("EGG", 0)``.
        inventory: A mapping of resource name to the market's current
            supply of it. This is the shared market's own stockpile
            (what drives the price curve), distinct from anything
            Dimitri or the opponent personally holds.
    """

    prices: Mapping[str, int]
    inventory: Mapping[str, int]
