"""Simulates the immediate effect of a single action on the GameState.

Simulator answers one question: given the current GameState and ONE
candidate Action, what does the state look like immediately afterwards,
considering only the effects Dimitri's current models can represent
directly? It applies the observable effects of BUY_PRODUCT and SELL
(money, shed inventory, and market inventory and prices), of BUY_SEED
(money and seeds), of PLANT, WATER, and HARVEST (seeds, the farm tile
under the acting unit, and what it carries), of DROP (what the acting
unit carries and the shed), and of movement (the acting unit's
position), and nothing else.
Other Kaggriculture actions (BUY_ANIMAL, HIRE, BUY_LAND) are rejected as
unsupported until their costs are represented.

PLANT follows the environment's rules (see dimitri.planner.rules): the
acting unit plants exactly one seed on the tile it stands on, which
must be empty and unlocked, and that tile becomes a new PlantTile.
Money, the shed, and unit inventories are untouched.

WATER marks the plant under the acting unit as watered today and, for a
one-time crop inside its watering window, adds the environment's yield
bonus. HARVEST moves a ready plant's whole yield into the acting unit's
carried inventory; a one-time crop leaves an empty tile, an ongoing crop
stays with no yield. DROP, from an unlocked shed-access tile, moves the
acting unit's carried items into the shed until it is full and discards
the rest, emptying the unit's inventory. Harvesting animals is not
simulated. Each rejects an action the environment would ignore.

NORTH, SOUTH, EAST, and WEST move the acting unit one tile. The farmer
and hands follow the same rule: any in-bounds tile may be entered,
including LOCKED tiles, occupied tiles, and tiles where another unit
stands. A move off the board is rejected, because the environment would
ignore it and leave the unit where it is.

BUY_PRODUCT and SELL follow the environment's market rules (see
dimitri.planner.rules). An order is filled one unit at a time, and
each unit is priced from the market inventory at that moment, so a
multi-unit order moves the price as it fills. Only WHEAT and FERTILIZER
can be bought, and only market products can be sold. A purchase stops
when money runs short or the shed is full. A sale stops when the shed
runs out of the item. A partially filled order is a valid result. An
order that would fill no units at all is rejected, because the
environment would ignore it. The traded item's displayed price is then
refreshed from its new inventory, as the environment does after every
order. The opponent is assumed to place no competing orders, and town
consumption, which happens after the market phase, is not simulated.

BUY_SEED follows the environment's ``_commit_unit``: it is filled one
seed at a time at the crop's fixed seed price (CROPS), which does not
depend on the market. Each seed goes straight to the player's seeds;
the shed, market, unit inventories, and farm are untouched, and there
is no capacity limit. A purchase stops when money runs short, and an
order that would buy no seed at all is rejected.

simulate_turn applies every action in a Turn in the order Kaggriculture
does: the farmer, then each hand, then the market orders. It is the
action phase of a turn only: time does not advance.

advance_turn applies the rest of a game turn, as the environment does
after the market (see dimitri.planner.time_rules): town consumption and
price refresh, plant decay, the end-of-day sweep on the day's last
turn, and the step, day, and hour moving on by one turn. It is the only
place time advances. play_turn is one complete game turn:
simulate_turn followed by advance_turn. simulate_plan plays a Plan's
turns in order with play_turn, producing a hypothetical future
GameState; it never judges whether that future is desirable. The opponent is assumed to do
nothing, and random weed spawns and town-shop unlocks are not modelled.

It never chooses, ranks, or scores actions, and never models price
forecasts or opponent behavior.
Evaluation belongs to the Evaluator and selection to the Executive
downstream.

Simulation is copy-on-write: every rule builds new mappings, sequences,
and dataclasses for what it changes and never mutates the state it is
given in place. So the intermediate states of one call share unchanged
containers, and raw_observation, which simulation never reads or
changes, with the input instead of each being deep-copied. Only the
GameState a public method returns is isolated, once per call: it is a
deep copy with its own copy of raw_observation, so callers see exactly
the isolation described below. ``play_turn(..., isolated=False)`` skips
that copy for callers that chain many turns, and ``isolate`` provides it
for the last state of such a chain.

The input GameState is never mutated. The returned GameState is built
from a deep copy, so no mutable mapping or sequence is shared between
the original and the simulated state. A tile grid changed by PLANT is
rebuilt as a tuple of tuples.
"""

import copy
from dataclasses import replace

from dimitri.models.farm import Farm, TileValue
from dimitri.models.game_state import GameState
from dimitri.models.inventory import Inventory
from dimitri.models.opponent import Opponent
from dimitri.models.player import Player
from dimitri.planner.action import (
    BUY_PRODUCT,
    BUY_SEED,
    DROP,
    HARVEST,
    WATER,
    MARKET_ACTION_TYPES,
    MOVEMENT_ACTION_TYPES,
    PLANT,
    SELL,
    Action,
)
from dimitri.planner.rules import (
    FARMER,
    buy_quote,
    carried_items,
    drop_blocker,
    harvest_blocker,
    harvested_tile,
    shed_after_drop,
    water_blocker,
    watered_plant,
    market_price,
    move_destination,
    new_plant,
    plant_blocker,
    sell_quote,
    tile_under,
    unit_position,
)
from dimitri.planner.plan import Plan
from dimitri.planner.time_rules import (
    farm_after_turn,
    is_last_turn_of_day,
    refreshed_prices,
    town_consumption,
)
from dimitri.planner.turn import Turn
from dimitri.utils.constants import (
    BUYABLE_PRODUCTS,
    CROPS,
    MAX_MARKET_ORDERS_PER_TURN,
    PRODUCTS,
    SHED_CAPACITY,
    TURNS_PER_DAY,
)


class Simulator:
    """Produces the hypothetical GameState after a supported action."""

    def simulate_plan(self, game_state: GameState, plan: Plan) -> GameState:
        """Return the GameState after playing every turn of ``plan`` in order.

        Each of ``plan.turns`` is played with ``play_turn`` on the state
        left by the previous one, so time advances exactly once per turn.
        Only the listed turns are played: the plan's horizon is not
        filled with idle turns. An empty plan returns an unchanged copy.

        Raises:
            ValueError: If a turn cannot be simulated from the state it
                is played on. The message names the turn's index in the
                plan; nothing is skipped or replaced with PASS.
        """
        state = game_state
        for index, turn in enumerate(plan.turns):
            try:
                state = self._play_turn(state, turn)
            except ValueError as exc:
                raise ValueError(f"Plan turn {index}: {exc}") from exc
        return _isolated(state, game_state)

    def play_turn(
        self, game_state: GameState, turn: Turn, *, isolated: bool = True
    ) -> GameState:
        """Return the GameState one complete game turn after playing ``turn``.

        This is ``simulate_turn`` followed by ``advance_turn``, so time
        advances exactly once.

        With ``isolated=False`` the result is not isolated: it is built
        copy-on-write from ``game_state`` and may share containers and
        raw_observation with it. That is for callers that chain many
        turns and keep only the last state, such as plan generators.
        Neither state may be mutated, and the last state of the chain
        must be passed to ``isolate`` before it is handed on.

        Raises:
            ValueError: As ``simulate_turn``.
        """
        result = self._play_turn(game_state, turn)
        return _isolated(result, game_state) if isolated else result

    def isolate(self, game_state: GameState) -> GameState:
        """Return an equal GameState that shares nothing mutable with ``game_state``.

        It gets its own copy of raw_observation, exactly as the result of
        any other public method does.
        """
        return _isolated(game_state, game_state)

    def _play_turn(self, game_state: GameState, turn: Turn) -> GameState:
        return self._advance_turn(self._simulate_turn(game_state, turn))

    def advance_turn(self, game_state: GameState) -> GameState:
        """Return ``game_state`` after the end-of-turn phase of its current turn.

        Applies what the environment does after the market, for the turn
        at ``game_state.step``: the town consumes from the market and
        every price is refreshed; plants on both farms decay; on the
        last turn of a day, both farms get the end-of-day sweep and
        Dimitri's carried items are dropped into the shed (overflow is
        discarded) and its unit inventories reset; then the step moves
        on by one and ``day`` and ``hour`` follow from it.
        """
        return _isolated(self._advance_turn(game_state), game_state)

    def _advance_turn(self, game_state: GameState) -> GameState:
        state = game_state
        step, day = state.step, state.day

        market_inventory = dict(state.market.inventory)
        for item, units in town_consumption(step, day, state.town.unlocked_shops).items():
            if item in market_inventory:
                market_inventory[item] -= units
        market = replace(
            state.market,
            inventory=market_inventory,
            prices=refreshed_prices(state.market.prices, market_inventory),
        )

        player = _with_farm(state.player, farm_after_turn(state.player.farm, step))
        if is_last_turn_of_day(step):
            shed = player.inventory.items
            for inventory in player.unit_inventories:
                shed = shed_after_drop(inventory.items, shed, SHED_CAPACITY)
            player = replace(
                player,
                inventory=Inventory(items=dict(shed)),
                unit_inventories=(Inventory(items={}),),
            )
        opponent = _with_farm(state.opponent, farm_after_turn(state.opponent.farm, step))

        next_step = step + 1
        return replace(
            state,
            step=next_step,
            day=next_step // TURNS_PER_DAY,
            hour=next_step % TURNS_PER_DAY,
            player=player,
            opponent=opponent,
            market=market,
        )

    def simulate_turn(self, game_state: GameState, turn: Turn) -> GameState:
        """Return a new GameState reflecting every action in ``turn``.

        Actions are applied in turn order, each to the state left by the
        previous one: the farmer acts as unit 0 and hand ``i`` as unit
        ``i + 1``. A passing hand (None) is skipped and left unchanged.
        An empty turn returns an unchanged copy.

        Raises:
            ValueError: If any action in ``turn`` cannot be simulated
                from the state it is applied to, or is in the wrong
                channel (a market action for a unit, or farm work in
                the market), or if the turn has more market orders than
                the environment processes.
        """
        return _isolated(self._simulate_turn(game_state, turn), game_state)

    def _simulate_turn(self, game_state: GameState, turn: Turn) -> GameState:
        if len(turn.market) > MAX_MARKET_ORDERS_PER_TURN:
            raise ValueError(
                f"At most {MAX_MARKET_ORDERS_PER_TURN} market orders are processed "
                f"per turn, got {len(turn.market)}"
            )
        state = game_state
        units = [] if turn.farmer is None else [(FARMER, turn.farmer)]
        units += [
            (index + 1, hand)
            for index, hand in enumerate(turn.hands)
            if hand is not None
        ]
        for unit, action in units:
            if action.action_type in MARKET_ACTION_TYPES:
                raise ValueError(
                    f"Market action {action.action_type!r} cannot be performed by a unit"
                )
            state = self._simulate_action(state, action, unit)
        for action in turn.market:
            if action.action_type not in MARKET_ACTION_TYPES:
                raise ValueError(
                    f"{action.action_type!r} is not a market action"
                )
            state = self._simulate_action(state, action, FARMER)
        return state

    def simulate(
        self, game_state: GameState, action: Action, *, unit: int = FARMER
    ) -> GameState:
        """Return a new GameState reflecting the immediate effect of ``action``.

        Args:
            game_state: The state to apply ``action`` to.
            action: The action to simulate.
            unit: The unit performing farm work or movement: 0 for the main farmer,
                ``i + 1`` for the hand at ``farm.hands[i]``. Ignored
                for market actions.

        Raises:
            ValueError: If the action type is unsupported, or the action
                is invalid for ``game_state`` (missing target, unknown
                item, invalid quantity, insufficient money, items, or
                seeds, or a PLANT the environment would ignore).
        """
        return _isolated(self._simulate_action(game_state, action, unit), game_state)

    def _simulate_action(self, game_state: GameState, action: Action, unit: int) -> GameState:
        if action.action_type == BUY_PRODUCT:
            return self._buy_product(game_state, action)
        if action.action_type == SELL:
            return self._sell(game_state, action)
        if action.action_type == BUY_SEED:
            return self._buy_seed(game_state, action)
        if action.action_type == PLANT:
            return self._plant(game_state, action, unit)
        if action.action_type in MOVEMENT_ACTION_TYPES:
            return self._move(game_state, action, unit)
        if action.action_type == WATER:
            return self._water(game_state, action, unit)
        if action.action_type == HARVEST:
            return self._harvest(game_state, action, unit)
        if action.action_type == DROP:
            return self._drop(game_state, action, unit)
        raise ValueError(f"Unsupported action type: {action.action_type!r}")

    @staticmethod
    def _buy_product(game_state: GameState, action: Action) -> GameState:
        _require_target_and_quantity(action)
        item = action.target
        if item not in BUYABLE_PRODUCTS:
            raise ValueError(f"{item!r} cannot be bought with {BUY_PRODUCT}")
        _require_market_inventory(game_state, item)

        new_state = game_state
        money = new_state.player.money
        shed = dict(new_state.player.inventory.items)
        market_inventory = dict(new_state.market.inventory)

        bought = 0
        stop_reason = None
        while bought < action.quantity:
            price = buy_quote(item, market_inventory[item])
            if money < price:
                stop_reason = f"Cannot afford {item!r} at {price}: have {money}"
                break
            if sum(shed.values()) >= SHED_CAPACITY:
                stop_reason = f"Shed is full ({SHED_CAPACITY} items)"
                break
            money -= price
            shed[item] = shed.get(item, 0) + 1
            market_inventory[item] -= 1
            bought += 1
        if bought == 0:
            raise ValueError(stop_reason)

        return _with_trade(new_state, money, shed, market_inventory, item)

    @staticmethod
    def _sell(game_state: GameState, action: Action) -> GameState:
        _require_target_and_quantity(action)
        item = action.target
        if item not in PRODUCTS:
            raise ValueError(f"{item!r} cannot be sold with {SELL}")
        _require_market_inventory(game_state, item)
        if game_state.player.inventory.items.get(item, 0) <= 0:
            raise ValueError(f"Cannot sell {item!r}: none in the shed")

        new_state = game_state
        money = new_state.player.money
        shed = dict(new_state.player.inventory.items)
        market_inventory = dict(new_state.market.inventory)

        for _ in range(action.quantity):
            if shed.get(item, 0) <= 0:
                break
            price = sell_quote(item, market_inventory[item])
            shed[item] -= 1
            money += price
            # The environment does not add sales at the price floor to supply.
            if price > 1:
                market_inventory[item] += 1

        return _with_trade(new_state, money, shed, market_inventory, item)

    @staticmethod
    def _buy_seed(game_state: GameState, action: Action) -> GameState:
        crop = action.target
        if crop not in CROPS:
            raise ValueError(f"{crop!r} cannot be bought with {BUY_SEED}")
        quantity = action.quantity
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ValueError(
                f"{BUY_SEED} quantity must be a positive integer, got {quantity!r}"
            )

        price = CROPS[crop].seed_price
        money = game_state.player.money
        bought = min(quantity, money // price)
        if bought == 0:
            raise ValueError(f"Cannot afford {crop!r} seed at {price}: have {money}")

        new_state = game_state
        seeds = dict(new_state.player.seeds)
        seeds[crop] = seeds.get(crop, 0) + bought
        player = replace(
            new_state.player, money=money - bought * price, seeds=seeds
        )
        return replace(new_state, player=player)

    @staticmethod
    def _move(game_state: GameState, action: Action, unit: int) -> GameState:
        if action.target is not None:
            raise ValueError(f"{action.action_type} takes no target")
        if action.quantity != 1 or isinstance(action.quantity, bool):
            raise ValueError(
                f"{action.action_type} moves exactly one tile, "
                f"got quantity {action.quantity!r}"
            )
        x, y = move_destination(game_state.player.farm, unit, action.action_type)

        new_state = game_state
        farm = new_state.player.farm
        if unit == FARMER:
            farm = replace(farm, farmer=[x, y])
        else:
            hands = [list(position) for position in farm.hands]
            hands[unit - 1] = [x, y]
            farm = replace(farm, hands=hands)
        player = replace(new_state.player, farm=farm)
        return replace(new_state, player=player)

    @staticmethod
    def _water(game_state: GameState, action: Action, unit: int) -> GameState:
        _require_bare_unit_op(action)
        blocker = water_blocker(game_state, unit)
        if blocker is not None:
            raise ValueError(blocker)

        new_state = game_state
        plant = tile_under(new_state.player.farm, unit)
        farm = _with_tile_under(
            new_state.player.farm, unit, watered_plant(plant, new_state.day)
        )
        return replace(new_state, player=replace(new_state.player, farm=farm))

    @staticmethod
    def _harvest(game_state: GameState, action: Action, unit: int) -> GameState:
        _require_bare_unit_op(action)
        blocker = harvest_blocker(game_state, unit)
        if blocker is not None:
            raise ValueError(blocker)

        new_state = game_state
        player = new_state.player
        plant = tile_under(player.farm, unit)
        carried = dict(carried_items(player, unit))
        carried[plant.crop] = carried.get(plant.crop, 0) + plant.yield_units
        player = replace(
            player,
            farm=_with_tile_under(player.farm, unit, harvested_tile(plant)),
            unit_inventories=_with_carried(player, unit, carried),
        )
        return replace(new_state, player=player)

    @staticmethod
    def _drop(game_state: GameState, action: Action, unit: int) -> GameState:
        _require_bare_unit_op(action)
        blocker = drop_blocker(game_state, unit)
        if blocker is not None:
            raise ValueError(blocker)

        new_state = game_state
        player = new_state.player
        shed = shed_after_drop(
            carried_items(player, unit), player.inventory.items, SHED_CAPACITY
        )
        player = replace(
            player,
            inventory=Inventory(items=shed),
            unit_inventories=_with_carried(player, unit, {}),
        )
        return replace(new_state, player=player)

    @staticmethod
    def _plant(game_state: GameState, action: Action, unit: int) -> GameState:
        if action.target is None:
            raise ValueError(f"{action.action_type} action requires a target")
        if action.quantity != 1 or isinstance(action.quantity, bool):
            raise ValueError(
                f"{action.action_type} plants exactly one seed, "
                f"got quantity {action.quantity!r}"
            )
        blocker = plant_blocker(game_state, action.target, unit)
        if blocker is not None:
            raise ValueError(blocker)

        new_state = game_state
        seeds = dict(new_state.player.seeds)
        seeds[action.target] -= 1

        farm = new_state.player.farm
        x, y = unit_position(farm, unit)
        tiles = tuple(tuple(row) for row in farm.tiles)
        row = list(tiles[y])
        row[x] = new_plant(action.target, new_state.day)
        tiles = (*tiles[:y], tuple(row), *tiles[y + 1 :])

        player = replace(
            new_state.player, seeds=seeds, farm=replace(farm, tiles=tiles)
        )
        return replace(new_state, player=player)

def _with_farm(owner: Player | Opponent, farm: Farm) -> Player | Opponent:
    """Return ``owner`` (a Player or Opponent) holding ``farm``.

    When ``farm`` is the farm ``owner`` already holds, ``owner`` itself is
    returned: it is equal to a rebuilt one, and nothing in simulation
    mutates it.
    """
    return owner if farm is owner.farm else replace(owner, farm=farm)


def _isolated(result: GameState, source: GameState) -> GameState:
    """Return ``result`` sharing nothing mutable with ``source`` or with any other state.

    Every field but raw_observation is deep-copied, and raw_observation
    becomes its own deep copy of ``source``'s, which simulation never
    changes. Copying them separately keeps the parsed state's lists
    independent of the observation dicts they were parsed from.
    """
    return _with_own_observation(_working_copy(result), source)


def _working_copy(game_state: GameState) -> GameState:
    """Return a deep copy of ``game_state`` that shares its raw_observation."""
    raw = game_state.raw_observation
    return copy.deepcopy(game_state, {id(raw): raw})


def _with_own_observation(result: GameState, source: GameState) -> GameState:
    """Return ``result`` with its own deep copy of ``source``'s raw_observation."""
    return replace(result, raw_observation=copy.deepcopy(source.raw_observation))


def _require_bare_unit_op(action: Action) -> None:
    if action.target is not None:
        raise ValueError(f"{action.action_type} takes no target")
    if action.quantity != 1 or isinstance(action.quantity, bool):
        raise ValueError(
            f"{action.action_type} is a single-unit action, "
            f"got quantity {action.quantity!r}"
        )


def _with_tile_under(farm: Farm, unit: int, tile: TileValue) -> Farm:
    """Return ``farm`` with the tile under ``unit`` replaced, as a tuple grid."""
    x, y = unit_position(farm, unit)
    tiles = tuple(tuple(row) for row in farm.tiles)
    row = list(tiles[y])
    row[x] = tile
    return replace(farm, tiles=(*tiles[:y], tuple(row), *tiles[y + 1 :]))


def _with_carried(
    player: Player, unit: int, items: dict[str, int]
) -> tuple[Inventory, ...]:
    """Return the unit inventories with ``unit`` carrying ``items``.

    Like the environment, missing entries up to ``unit`` are added empty.
    """
    inventories = list(player.unit_inventories)
    while len(inventories) <= unit:
        inventories.append(Inventory(items={}))
    inventories[unit] = Inventory(items=items)
    return tuple(inventories)


def _require_target_and_quantity(action: Action) -> None:
    if action.target is None:
        raise ValueError(f"{action.action_type} action requires a target")
    if action.quantity <= 0:
        raise ValueError(
            f"{action.action_type} quantity must be positive, got {action.quantity}"
        )


def _require_market_inventory(game_state: GameState, item: str) -> None:
    if item not in game_state.market.inventory:
        raise ValueError(f"No market inventory for {item!r}")


def _with_trade(
    state: GameState,
    money: int,
    shed: dict[str, int],
    market_inventory: dict[str, int],
    item: str,
) -> GameState:
    """Return ``state`` with a filled market order's results applied."""
    prices = dict(state.market.prices)
    prices[item] = market_price(item, market_inventory[item])
    player = replace(state.player, money=money, inventory=Inventory(items=shed))
    market = replace(state.market, prices=prices, inventory=market_inventory)
    return replace(state, player=player, market=market)
