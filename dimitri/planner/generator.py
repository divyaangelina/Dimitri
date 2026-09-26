"""Generates the candidate actions available from the current GameState.

CandidateGenerator enumerates the actions Dimitri could take right now,
using only facts directly observable in the GameState. It considers
possibilities; it never ranks, scores, simulates, or chooses among them.
Selection belongs to the Executive downstream.
"""

from dimitri.models.game_state import GameState
from dimitri.planner.action import Action


class CandidateGenerator:
    """Enumerates valid single-unit BUY, SELL, and PLANT actions.

    Actions are returned in a deterministic order: all BUY actions, then
    all SELL actions, then all PLANT actions. Within each category the
    order of the underlying GameState mapping is preserved.
    """

    def generate(self, game_state: GameState) -> tuple[Action, ...]:
        """Return every candidate action available in ``game_state``."""
        return (
            *self._buy_actions(game_state),
            *self._sell_actions(game_state),
            *self._plant_actions(game_state),
        )

    @staticmethod
    def _buy_actions(game_state: GameState) -> list[Action]:
        money = game_state.player.money
        return [
            Action(action_type="BUY", target=item, quantity=1)
            for item, price in game_state.market.prices.items()
            if price <= money
        ]

    @staticmethod
    def _sell_actions(game_state: GameState) -> list[Action]:
        prices = game_state.market.prices
        return [
            Action(action_type="SELL", target=item, quantity=1)
            for item, quantity in game_state.player.inventory.items.items()
            if quantity > 0 and item in prices
        ]

    @staticmethod
    def _plant_actions(game_state: GameState) -> list[Action]:
        return [
            Action(action_type="PLANT", target=crop, quantity=1)
            for crop, quantity in game_state.player.seeds.items()
            if quantity > 0
        ]
