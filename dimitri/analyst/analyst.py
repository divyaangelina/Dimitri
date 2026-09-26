"""Turns a trusted GameState into deterministic derived facts.

The Analyst sits between the Observer and the Planner in Dimitri's
pipeline:

    Observer -> GameState -> Analyst -> Analysis -> Planner

It reads a GameState and computes facts that follow directly from it
(days remaining, tile counts, and so on), returning them as an
immutable Analysis. It never chooses crops or animals, recommends
actions, calculates ROI, ranks investments, predicts prices, analyzes
opponent strategy, simulates future states, or builds plans. It also
never modifies the GameState or its raw observation.
"""

from collections.abc import Mapping
from types import MappingProxyType

from dimitri.analyst.analysis import Analysis
from dimitri.analyst.opportunity import EconomicOpportunity
from dimitri.models.game_state import GameState
from dimitri.utils.constants import SEASON_LENGTH_DAYS


class Analyst:
    """Derives deterministic facts from a GameState.

    Analyst holds no state between calls; each call to analyze depends
    only on the GameState passed in.
    """

    def analyze(self, game_state: GameState) -> Analysis:
        """Compute an Analysis from a GameState without modifying it.

        Args:
            game_state: The validated GameState to analyze.

        Returns:
            An Analysis containing the facts derived from game_state.
        """
        locked = 0
        occupied = 0
        empty = 0
        for row in game_state.player.farm.tiles:
            for tile in row:
                if tile is None:
                    empty += 1
                elif tile == "LOCKED":
                    locked += 1
                elif isinstance(tile, Mapping):
                    occupied += 1

        prices = MappingProxyType(dict(game_state.market.prices))
        market_inventory = MappingProxyType(dict(game_state.market.inventory))

        return Analysis(
            current_day=game_state.day,
            current_hour=game_state.hour,
            days_remaining=SEASON_LENGTH_DAYS - game_state.day,
            current_money=game_state.player.money,
            unlocked_tiles=empty + occupied,
            locked_tiles=locked,
            occupied_tiles=occupied,
            empty_tiles=empty,
            market_prices=prices,
            market_inventory=market_inventory,
            inventory_total_value=_priced_total(
                game_state.player.inventory.items, prices
            ),
            seed_total_cost=_priced_total(game_state.player.seeds, prices),
            economic_opportunities=_economic_opportunities(prices),
        )


def _priced_total(quantities: Mapping[str, int], prices: Mapping[str, int]) -> int:
    """Sum quantity * price over the entries that have a market price."""
    return sum(
        quantity * prices[name]
        for name, quantity in quantities.items()
        if name in prices
    )


def _economic_opportunities(
    prices: Mapping[str, int],
) -> tuple[EconomicOpportunity, ...]:
    """Build one EconomicOpportunity per priced item, in price-mapping order.

    The GameState exposes a single price per item, so it serves as both
    the buy cost and the sell price.
    """
    opportunities = []
    for item, price in prices.items():
        buy_cost = price
        sell_price = price
        opportunities.append(
            EconomicOpportunity(
                item=item,
                buy_cost=buy_cost,
                sell_price=sell_price,
                gross_margin=sell_price - buy_cost,
            )
        )
    return tuple(opportunities)
