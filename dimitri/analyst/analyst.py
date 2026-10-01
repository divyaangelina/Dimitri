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

from types import MappingProxyType

from dimitri.analyst.analysis import Analysis
from dimitri.models.game_state import GameState
from dimitri.utils.constants import SEASON_LENGTH_DAYS
from dimitri.utils.valuation import market_value, seed_cost


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
                else:
                    # A PlantTile, AnimalTile, StructureTile, or WeedTile.
                    occupied += 1

        prices = MappingProxyType(dict(game_state.market.prices))
        market_inventory = MappingProxyType(dict(game_state.market.inventory))
        money = game_state.player.money
        inventory_total_value = market_value(
            game_state.player.inventory.items, prices
        )
        seed_total_cost = seed_cost(game_state.player.seeds)

        return Analysis(
            current_day=game_state.day,
            current_hour=game_state.hour,
            days_remaining=SEASON_LENGTH_DAYS - game_state.day,
            current_money=money,
            unlocked_tiles=empty + occupied,
            locked_tiles=locked,
            occupied_tiles=occupied,
            empty_tiles=empty,
            market_prices=prices,
            market_inventory=market_inventory,
            inventory_total_value=inventory_total_value,
            seed_total_cost=seed_total_cost,
            cash_plus_inventory_value=money + inventory_total_value,
            cash_after_seed_replacement=money - seed_total_cost,
            affordable_market_items=tuple(
                item for item, price in prices.items() if price <= money
            ),
            has_empty_farm_capacity=empty > 0,
        )

