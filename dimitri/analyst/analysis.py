"""Represents the Analyst's derived facts about a single GameState.

Analysis holds deterministic facts computed directly from a GameState:
values that follow from the observed data with no judgement involved,
such as how many days remain in the season or how many farm tiles are
currently empty. It is the Analyst's output and the input the Planner
will later read.

Analysis stores derived facts only. It never contains recommendations,
rankings, ROI figures, predictions, or plans — those responsibilities
belong to the Planner and Executive modules downstream.

Because it is a frozen dataclass, an Analysis instance cannot be
mutated after construction. Each new GameState produces a new Analysis
rather than modifying an existing one.
"""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Analysis:
    """An immutable set of deterministic facts derived from a GameState.

    Attributes:
        current_day: The current in-game day (zero-indexed), copied
            from GameState.day.
        current_hour: The current turn within the day, copied from
            GameState.hour.
        days_remaining: The number of days left in the season,
            including the current day.
        current_money: Dimitri's current bank balance, in coins.
        unlocked_tiles: The number of tiles on Dimitri's farm that are
            not ``"LOCKED"`` (both empty and occupied).
        locked_tiles: The number of ``"LOCKED"`` tiles on Dimitri's
            farm.
        occupied_tiles: The number of tiles on Dimitri's farm holding
            a plant, weed, or animal structure.
        empty_tiles: The number of unlocked tiles on Dimitri's farm
            with nothing on them.
        market_prices: A read-only snapshot of the current market
            prices, copied from GameState.market.prices.
        market_inventory: A read-only snapshot of the market's current
            supply, copied from GameState.market.inventory.
        inventory_total_value: The theoretical sale value of Dimitri's
            shed inventory at current market prices: the sum of
            quantity * price over items that have a market price.
            Unpriced items contribute nothing. This is an accounting
            fact, not a profit or expected-value figure.
        seed_total_cost: The theoretical replacement cost of Dimitri's
            held seeds at current market prices: the sum of
            quantity * price over seed crops that have a market price.
            Unpriced seeds contribute nothing.
    """

    current_day: int
    current_hour: int
    days_remaining: int
    current_money: int
    unlocked_tiles: int
    locked_tiles: int
    occupied_tiles: int
    empty_tiles: int
    market_prices: Mapping[str, int]
    market_inventory: Mapping[str, int]
    inventory_total_value: int
    seed_total_cost: int
