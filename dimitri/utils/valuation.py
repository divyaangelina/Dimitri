"""The accounting valuations shared by the Analyst and the Evaluator.

These are the single definitions of what held goods and held seeds are
worth, so every module that reports them uses the same rule. They are
accounting facts, not profit or expected-value estimates.
"""

from collections.abc import Mapping

from dimitri.utils.constants import CROPS


def market_value(quantities: Mapping[str, int], prices: Mapping[str, int]) -> int:
    """Sum quantity * price over the entries that have a market price.

    Items without a price contribute nothing.
    """
    return sum(
        quantity * prices[name]
        for name, quantity in quantities.items()
        if name in prices
    )


def seed_cost(seeds: Mapping[str, int]) -> int:
    """Return what ``seeds`` would cost to buy again at the fixed seed prices.

    Seed prices come from CROPS, never from market sale prices. Seeds of
    an unknown crop contribute nothing.
    """
    return sum(
        quantity * CROPS[crop].seed_price
        for crop, quantity in seeds.items()
        if crop in CROPS
    )
