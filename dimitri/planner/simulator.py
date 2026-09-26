"""Simulates the immediate effect of a single action on the GameState.

Simulator answers one question: given the current GameState and ONE
candidate Action, what does the state look like immediately afterwards,
considering only the effects Dimitri's current models can represent
directly? It applies the observable accounting effects of BUY, SELL,
and PLANT — money, shed inventory, and seed counts — and nothing else.

It never chooses, ranks, or scores actions, never advances time, and
never models crop growth, tile placement, market reactions, or opponent
behavior. Evaluation belongs to the Evaluator and selection to the
Executive downstream.

The input GameState is never mutated. The returned GameState is built
from a deep copy, so no mutable mapping or sequence is shared between
the original and the simulated state.
"""

import copy
from dataclasses import replace

from dimitri.models.game_state import GameState
from dimitri.models.inventory import Inventory
from dimitri.planner.action import Action


class Simulator:
    """Produces the hypothetical GameState after a single BUY, SELL, or PLANT."""

    def simulate(self, game_state: GameState, action: Action) -> GameState:
        """Return a new GameState reflecting the immediate effect of ``action``.

        Raises:
            ValueError: If the action type is unsupported, or the action
                is invalid for ``game_state`` (missing target, unknown
                item, non-positive quantity, insufficient money, items,
                or seeds).
        """
        if action.action_type == "BUY":
            return self._buy(game_state, action)
        if action.action_type == "SELL":
            return self._sell(game_state, action)
        if action.action_type == "PLANT":
            return self._plant(game_state, action)
        raise ValueError(f"Unsupported action type: {action.action_type!r}")

    @staticmethod
    def _buy(game_state: GameState, action: Action) -> GameState:
        _require_target_and_quantity(action)
        price = _require_price(game_state, action)
        cost = price * action.quantity
        if cost > game_state.player.money:
            raise ValueError(
                f"Cannot afford {action.quantity} x {action.target!r}: "
                f"costs {cost}, have {game_state.player.money}"
            )

        new_state = copy.deepcopy(game_state)
        items = dict(new_state.player.inventory.items)
        items[action.target] = items.get(action.target, 0) + action.quantity
        player = replace(
            new_state.player,
            money=new_state.player.money - cost,
            inventory=Inventory(items=items),
        )
        return replace(new_state, player=player)

    @staticmethod
    def _sell(game_state: GameState, action: Action) -> GameState:
        _require_target_and_quantity(action)
        price = _require_price(game_state, action)
        owned = game_state.player.inventory.items.get(action.target, 0)
        if owned < action.quantity:
            raise ValueError(
                f"Cannot sell {action.quantity} x {action.target!r}: own {owned}"
            )

        new_state = copy.deepcopy(game_state)
        items = dict(new_state.player.inventory.items)
        items[action.target] = owned - action.quantity
        player = replace(
            new_state.player,
            money=new_state.player.money + price * action.quantity,
            inventory=Inventory(items=items),
        )
        return replace(new_state, player=player)

    @staticmethod
    def _plant(game_state: GameState, action: Action) -> GameState:
        _require_target_and_quantity(action)
        if action.target not in game_state.player.seeds:
            raise ValueError(f"Unknown seed type: {action.target!r}")
        owned = game_state.player.seeds[action.target]
        if owned < action.quantity:
            raise ValueError(
                f"Cannot plant {action.quantity} x {action.target!r}: "
                f"own {owned} seeds"
            )

        new_state = copy.deepcopy(game_state)
        seeds = dict(new_state.player.seeds)
        seeds[action.target] = owned - action.quantity
        player = replace(new_state.player, seeds=seeds)
        return replace(new_state, player=player)


def _require_target_and_quantity(action: Action) -> None:
    if action.target is None:
        raise ValueError(f"{action.action_type} action requires a target")
    if action.quantity <= 0:
        raise ValueError(
            f"{action.action_type} quantity must be positive, got {action.quantity}"
        )


def _require_price(game_state: GameState, action: Action) -> int:
    try:
        return game_state.market.prices[action.target]
    except KeyError:
        raise ValueError(f"No market price for {action.target!r}") from None
