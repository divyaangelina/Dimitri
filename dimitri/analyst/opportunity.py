"""Represents a single market item's economic opportunity facts.

An EconomicOpportunity records the per-unit buy cost, sell price, and
gross margin of one market item as observed in the current GameState.
These are accounting facts, not judgements: the Analyst never ranks
opportunities or recommends which to act on.

The current GameState exposes a single market price per item, so
buy_cost and sell_price are both that price and gross_margin is
normally zero. The structure exists so future market data with
distinct buy and sell prices can populate it without changing callers.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EconomicOpportunity:
    """Immutable per-unit economic facts for one market item.

    Attributes:
        item: The market item name, as keyed in GameState.market.prices.
        buy_cost: The current market price of one unit of the item.
        sell_price: The current market price of one unit of the item.
        gross_margin: sell_price - buy_cost.
    """

    item: str
    buy_cost: int
    sell_price: int
    gross_margin: int
