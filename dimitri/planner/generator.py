"""Generates the candidate actions available from the current GameState.

CandidateGenerator enumerates the actions Dimitri could take right now,
using only facts directly observable in the GameState. It considers
possibilities; it never ranks, scores, simulates, or chooses among them.
Selection belongs to the Executive downstream.
"""

from dimitri.models.game_state import GameState
from dimitri.planner.action import (
    BUY_PRODUCT,
    BUY_SEED,
    DROP,
    HARVEST,
    PLANT,
    SELL,
    WATER,
    Action,
)
from dimitri.planner.rules import (
    FARMER,
    buy_quote,
    drop_blocker,
    harvest_blocker,
    plant_blocker,
    water_blocker,
)
from dimitri.utils.constants import BUYABLE_PRODUCTS, CROPS, PRODUCTS, SHED_CAPACITY


class CandidateGenerator:
    """Enumerates valid single-unit market orders and farmer farm work.

    It generates BUY_PRODUCT, BUY_SEED, SELL, and, for the farmer, PLANT,
    WATER, HARVEST, and DROP, each only when the environment would apply
    it.

    BUY_ANIMAL, HIRE, and BUY_LAND are not generated: their costs are
    not yet represented in the GameState.

    Actions are returned in a deterministic order: all BUY_PRODUCT
    actions, then all BUY_SEED actions, then all SELL actions, then all
    PLANT actions, then WATER, HARVEST, and DROP. Within each category the order of the underlying
    mapping (the GameState's, or CROPS for BUY_SEED) is preserved.
    """

    def generate(self, game_state: GameState) -> tuple[Action, ...]:
        """Return every candidate action available in ``game_state``."""
        return (
            *self._buy_product_actions(game_state),
            *self._buy_seed_actions(game_state),
            *self._sell_actions(game_state),
            *self._plant_actions(game_state),
            *self._unit_op_actions(game_state),
        )

    @staticmethod
    def _buy_product_actions(game_state: GameState) -> list[Action]:
        # Only purchases the environment would fill: a buyable product,
        # affordable at the environment's quote, with room in the shed.
        money = game_state.player.money
        market_inventory = game_state.market.inventory
        if sum(game_state.player.inventory.items.values()) >= SHED_CAPACITY:
            return []
        return [
            Action(action_type=BUY_PRODUCT, target=item, quantity=1)
            for item in game_state.market.prices
            if item in BUYABLE_PRODUCTS
            and item in market_inventory
            and buy_quote(item, market_inventory[item]) <= money
        ]

    @staticmethod
    def _buy_seed_actions(game_state: GameState) -> list[Action]:
        # Only purchases the environment would fill: one seed of a known
        # crop the player can afford.
        money = game_state.player.money
        return [
            Action(action_type=BUY_SEED, target=crop, quantity=1)
            for crop, rules in CROPS.items()
            if rules.seed_price <= money
        ]

    @staticmethod
    def _sell_actions(game_state: GameState) -> list[Action]:
        # Only sales the environment would fill: a market product held in the shed.
        market_inventory = game_state.market.inventory
        return [
            Action(action_type=SELL, target=item, quantity=1)
            for item, quantity in game_state.player.inventory.items.items()
            if quantity > 0 and item in PRODUCTS and item in market_inventory
        ]

    @staticmethod
    def _plant_actions(game_state: GameState) -> list[Action]:
        # Only plants the environment would apply for the farmer: a known
        # crop, a held seed, and an empty unlocked tile under the farmer.
        return [
            Action(action_type=PLANT, target=crop, quantity=1)
            for crop in game_state.player.seeds
            if plant_blocker(game_state, crop, FARMER) is None
        ]

    @staticmethod
    def _unit_op_actions(game_state: GameState) -> list[Action]:
        # Only farm work the environment would apply for the farmer.
        blockers = {
            WATER: water_blocker,
            HARVEST: harvest_blocker,
            DROP: drop_blocker,
        }
        return [
            Action(action_type=action_type)
            for action_type, blocker in blockers.items()
            if blocker(game_state, FARMER) is None
        ]
