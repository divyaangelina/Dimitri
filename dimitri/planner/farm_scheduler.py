"""Realizes one economic hypothesis as Turns while keeping the existing farm alive.

The FarmScheduler answers one question: given the current GameState and
one concrete crop-investment hypothesis, which turns realize that
hypothesis while every productive plant already on the farm is kept
alive and its output harvested and sold? It sits between the
PlanGenerators and the Simulator:

    PlanGenerator   what economic hypothesis should be tested?
    FarmScheduler   how is it realized alongside the existing farm?
    Simulator       what happens?

It never decides whether a hypothesis is worth pursuing, and never
scores, ranks or compares futures. It knows the crops' factual care
rules, and nothing about profit.

Jobs are derived purely from the current GameState, every turn, and
never stored. For each living WHEAT or TOMATO plant on Dimitri's farm:

- WHEAT: water it if it has not been watered today, except right before
  a harvest the water would not enlarge; harvest it on the first turn it
  can be harvested.
- TOMATO: water it daily until its harvest day, letting yield accumulate,
  and harvest once on its harvest day: the day after its last *useful*
  production, which is the latest production refreshed in season whose
  harvest can still be walked back, dropped and sold by the season's
  last action. It is harvested earlier if it holds its maximum yield.
  A tomato with no useful production left and nothing on it is spent:
  it gets no care and is left to decay.

Each job has a priority, served in this order:

1. SURVIVAL: water a plant that dies tonight without it (unwatered for
   the rest of the day after a missed day, or planted today). A job the
   farmer cannot reach before the day ends is dropped: that plant cannot
   be saved.
2. VALUE: a harvest whose yield is lost if delayed: a decaying plant, a
   tomato on its harvest day or at its maximum yield, or any harvest on
   the season's last day.
3. CONSTRUCTION: plant the hypothesis's next seed, only if planting,
   the same-day water it needs and every other job due today still fit
   in the day's remaining turns, and only if the new plant can still
   produce something sellable.
4. ROUTINE: the rest: daily watering and harvests that can wait.

Within a priority, the nearest job from the farmer's position comes
first, then the lower row, then the lower column. The farmer does a job
when it stands on its tile, and otherwise takes one straight-line step
towards it (east or west first). Any tile can be entered, so no
pathfinding is needed. With no job due, the farmer waits; the night
returns it to the spawn tile and drops what it carries into the shed.

Market orders share the farmer's turns: seeds are bought in the
schedule's first turn, alongside the farmer's first action; a seed
bought in a turn cannot be planted until the next, because market orders
are applied after unit actions. The schedule ends by dropping carried
crops at the spawn tile and selling every unit of WHEAT and TOMATO in
the shed in the same turn, since the drop is applied before the sale.

A schedule is rejected (None) if a plant that still had value and could
be maintained dies, if the hypothesis's seeds cannot all be planted
usefully, or if its output cannot be sold by the season's last action.
Plants the farmer cannot reach before they die tonight are exempt: their
loss is not the hypothesis's doing.

Turns are chained on the Simulator copy-on-write
(``play_turn(..., isolated=False)``); the returned state is not isolated,
and the caller isolates it once before handing it on.
"""

from collections.abc import Iterable, Sequence, Set
from dataclasses import dataclass

from dimitri.models.game_state import GameState
from dimitri.models.tile import PlantTile, WeedTile
from dimitri.planner.action import (
    BUY_SEED,
    DROP,
    EAST,
    HARVEST,
    NORTH,
    PLANT,
    SELL,
    SOUTH,
    WATER,
    WEST,
    Action,
)
from dimitri.planner.rules import FARMER, carried_items, watered_plant
from dimitri.planner.simulator import Simulator
from dimitri.planner.time_rules import spawn_position
from dimitri.planner.turn import Turn
from dimitri.utils.constants import CROPS, LAST_ACTION_STEP, TURNS_PER_DAY

WHEAT = "WHEAT"
TOMATO = "TOMATO"
MANAGED_CROPS = (WHEAT, TOMATO)
"""The crops whose plants the scheduler tends and whose output it sells."""

SURVIVAL, VALUE, CONSTRUCTION, ROUTINE = range(4)
"""Job priorities, most urgent first."""

_ACTION_ORDER = {HARVEST: 0, WATER: 1, PLANT: 2}

Tile = tuple[int, int]


@dataclass(frozen=True)
class Job:
    """One action due on one tile today.

    Attributes:
        priority: SURVIVAL, VALUE, CONSTRUCTION or ROUTINE.
        tile: The ``(x, y)`` tile the action is done on.
        action: WATER, HARVEST or PLANT.
    """

    priority: int
    tile: Tile
    action: str

    def order(self, position: Sequence[int]) -> tuple:
        """The deterministic order of this job for a farmer at ``position``."""
        x, y = self.tile
        return (self.priority, _distance(position, self.tile), y, x, _ACTION_ORDER[self.action])


@dataclass(frozen=True)
class Hypothesis:
    """A concrete crop-investment hypothesis to realize.

    Attributes:
        crop: The crop planted by the hypothesis, or None if it plants nothing.
        plant: How many new plants of ``crop`` to plant from held seeds.
        buy: How many ``crop`` seeds to buy in the first turn.
        targets: The tiles of existing plants whose output the hypothesis
            realizes. The schedule ends once they, and every plant it
            planted, have been harvested for the last time and sold.
    """

    crop: str | None = None
    plant: int = 0
    buy: int = 0
    targets: tuple[Tile, ...] = ()


@dataclass(frozen=True)
class Schedule:
    """A realized hypothesis.

    Attributes:
        turns: The turns, in order.
        state: The state they lead to, not isolated.
    """

    turns: tuple[Turn, ...]
    state: GameState


class FarmScheduler:
    """Turns a hypothesis into turns, keeping every maintainable plant on the farm alive."""

    def __init__(self, simulator: Simulator | None = None):
        self._simulator = simulator if simulator is not None else Simulator()

    def schedule(self, game_state: GameState, hypothesis: Hypothesis) -> Schedule | None:
        """Return the schedule realizing ``hypothesis`` from ``game_state``, or None.

        None means the hypothesis cannot be realized without losing a
        maintainable plant, planting a seed uselessly, or missing the
        season's end. ``game_state`` is never mutated.
        """
        try:
            return _Run(self._simulator, game_state, hypothesis).run()
        except ValueError:
            return None


# --- facts derived from the GameState -----------------------------------


def living_plants(game_state: GameState, crop: str) -> list[Tile]:
    """Return the ``(x, y)`` of every living ``crop`` plant on Dimitri's farm, oldest first.

    A living plant is a PlantTile of ``crop``; weeds, empty tiles, and
    other crops are not. Ties in ``planted_day`` are broken by row, then
    column.
    """
    plants = [
        (tile.planted_day, y, x)
        for y, row in enumerate(game_state.player.farm.tiles)
        for x, tile in enumerate(row)
        if isinstance(tile, PlantTile) and tile.crop == crop
    ]
    return [(x, y) for _, y, x in sorted(plants)]


def planting_order(game_state: GameState) -> list[Tile]:
    """Return the empty unlocked tiles in planting order.

    Nearest the spawn tile first, so daily walks stay short; ties are
    broken by row, then column.
    """
    farm = game_state.player.farm
    spawn = spawn_position(farm)
    empty = [
        (x, y)
        for y, row in enumerate(farm.tiles)
        for x, tile in enumerate(row)
        if tile is None
    ]
    return sorted(empty, key=lambda p: (_distance(p, spawn), p[1], p[0]))


def production_days(plant: PlantTile) -> tuple[int, ...]:
    """Return the days whose end-of-day refresh gives an ongoing ``plant`` a production.

    Mirrors ``plant_at_end_of_day``: the plant produces when the day after
    the refresh is ``first_yield_day`` days after planting, and every
    ``interval`` days after, ``max_yield`` times in all. A one-time crop
    has none.
    """
    rules = CROPS[plant.crop]
    if not rules.ongoing:
        return ()
    first = plant.planted_day + rules.first_yield_day - 1
    return tuple(first + k * rules.interval for k in range(rules.max_yield))


def refreshed_in_season(day: int) -> bool:
    """Return whether the environment runs the end-of-day refresh closing ``day``."""
    return day * TURNS_PER_DAY + TURNS_PER_DAY - 1 <= LAST_ACTION_STEP


def tomato_harvest_day(plant: PlantTile, tile: Tile, spawn: Sequence[int]) -> int | None:
    """Return the day ``plant`` is harvested for its last useful production, or None.

    A production is useful if it is refreshed in season and its harvest,
    made at the start of the next day from the spawn tile, can be walked
    back, dropped and sold by the season's last action. Both conditions
    are upper bounds on the production's day, so the last useful
    production is the last of ``production_days`` up to the tighter bound.
    """
    rules = CROPS[plant.crop]
    if not rules.ongoing:
        return None
    walk = _distance(spawn, tile)
    first = plant.planted_day + rules.first_yield_day - 1
    latest = min(
        # refreshed_in_season(day): day * TURNS_PER_DAY + TURNS_PER_DAY - 1 <= LAST_ACTION_STEP
        (LAST_ACTION_STEP - TURNS_PER_DAY + 1) // TURNS_PER_DAY,
        # sold in time: (day + 1) * TURNS_PER_DAY + 2 * walk + 1 <= LAST_ACTION_STEP
        (LAST_ACTION_STEP - 2 * walk - 1) // TURNS_PER_DAY - 1,
    )
    if latest < first:
        return None
    last = min(rules.max_yield - 1, (latest - first) // rules.interval)
    return first + last * rules.interval + 1


def has_value(plant: PlantTile, tile: Tile, game_state: GameState) -> bool:
    """Return whether ``plant`` holds yield or can still produce something useful.

    Living wheat always holds yield. A tomato has value while it holds
    yield or before its harvest day.
    """
    if plant.yield_units > 0:
        return True
    if plant.crop != TOMATO:
        return True
    harvest_day = tomato_harvest_day(plant, tile, spawn_position(game_state.player.farm))
    return harvest_day is not None and game_state.day < harvest_day


def turns_left_today(game_state: GameState) -> int:
    """Return how many turns, the current one included, remain to act today."""
    return min(
        TURNS_PER_DAY - game_state.hour,
        LAST_ACTION_STEP + 1 - game_state.step,
    )


def plant_jobs(
    game_state: GameState, tile: Tile, plant: PlantTile, spawn: Sequence[int] | None = None
) -> list[Job]:
    """Return the jobs ``plant`` on ``tile`` needs today, by its crop's rules.

    Pure: derived only from the plant and the clock. Survival jobs the
    farmer cannot reach are not filtered here. ``spawn`` is the farm's
    spawn tile, if the caller already has it.
    """
    day, step = game_state.day, game_state.step
    rules = CROPS[plant.crop]
    harvestable = plant.yield_units > 0 and day - plant.planted_day >= rules.first_yield_day
    last_day = LAST_ACTION_STEP // TURNS_PER_DAY
    decaying = 0 <= plant.max_lifespan_step <= step
    water = Job(SURVIVAL if plant.consecutive_unwatered >= 1 else ROUTINE, tile, WATER)
    if plant.crop == WHEAT:
        water_adds = watered_plant(plant, day).yield_units > plant.yield_units
        if harvestable and (plant.watered_today or not water_adds):
            urgent = decaying or day == last_day
            return [Job(VALUE if urgent else ROUTINE, tile, HARVEST)]
        return [] if plant.watered_today else [water]
    if spawn is None:
        spawn = spawn_position(game_state.player.farm)
    harvest_day = tomato_harvest_day(plant, tile, spawn)
    if harvest_day is None or day >= harvest_day:
        return [Job(VALUE, tile, HARVEST)] if harvestable else []
    if harvestable and plant.yield_units >= rules.max_yield:
        return [Job(VALUE, tile, HARVEST)]
    return [] if plant.watered_today else [water]


def care_jobs(game_state: GameState) -> list[Job]:
    """Return every care job due today for the living WHEAT and TOMATO plants.

    Survival jobs the farmer cannot reach before the day ends are left
    out: those plants cannot be saved.
    """
    position = game_state.player.farm.farmer
    spawn = spawn_position(game_state.player.farm)
    left = turns_left_today(game_state)
    jobs = []
    for y, row in enumerate(game_state.player.farm.tiles):
        for x, tile in enumerate(row):
            if isinstance(tile, PlantTile) and tile.crop in MANAGED_CROPS:
                for job in plant_jobs(game_state, (x, y), tile, spawn):
                    if job.priority == SURVIVAL and _distance(position, job.tile) + 1 > left:
                        continue
                    jobs.append(job)
    return jobs


def unsavable_plants(game_state: GameState) -> set[Tile]:
    """Return the plants that die tonight and that the farmer cannot reach in time."""
    position = game_state.player.farm.farmer
    left = turns_left_today(game_state)
    return {
        job.tile
        for y, row in enumerate(game_state.player.farm.tiles)
        for x, tile in enumerate(row)
        if isinstance(tile, PlantTile) and tile.crop in MANAGED_CROPS
        for job in plant_jobs(game_state, (x, y), tile)
        if job.priority == SURVIVAL and _distance(position, job.tile) + 1 > left
    }


def tour_cost(start: Sequence[int], tiles: Iterable[Tile]) -> int:
    """Return the turns to visit ``tiles`` nearest-first from ``start``, one action on each."""
    remaining = set(tiles)
    position = tuple(start)
    cost = 0
    while remaining:
        nearest = min(remaining, key=lambda p: (_distance(position, p), p[1], p[0]))
        cost += _distance(position, nearest) + 1
        remaining.remove(nearest)
        position = nearest
    return cost


def daily_care_capacity(game_state: GameState, tiles: Sequence[Tile]) -> int:
    """Return how many of ``tiles``, taken in order, can be watered daily with the farm's plants.

    Counts the longest prefix of ``tiles`` whose daily watering tour from
    the spawn tile, together with every living plant that still has
    value, fits in one day's turns, leaving one turn spare.
    """
    farm = game_state.player.farm
    spawn = spawn_position(farm)
    existing = [
        (x, y)
        for y, row in enumerate(farm.tiles)
        for x, tile in enumerate(row)
        if isinstance(tile, PlantTile)
        and tile.crop in MANAGED_CROPS
        and has_value(tile, (x, y), game_state)
    ]
    count = 0
    for n in range(1, len(tiles) + 1):
        if tour_cost(spawn, existing + list(tiles[:n])) > TURNS_PER_DAY - 1:
            break
        count = n
    return count


def max_tomato_plantings(game_state: GameState) -> int:
    """Return a number no schedule from ``game_state`` can plant more tomatoes usefully than.

    A necessary condition, used only to skip wave sizes the FarmScheduler
    would reject anyway:

    - A tomato planted on a day is useful only if it can still produce
      something sellable. That is easiest on the spawn tile (distance 0)
      and only gets harder on farther tiles and later days, so no tomato
      is planted usefully after the last day that holds for the spawn tile.
    - Each planting takes a PLANT turn and a WATER turn on the same day,
      and plantings on distinct tiles need at least one move between
      them, so ``m`` plantings take at least ``3m - 1`` of a day's turns.

    Any wave larger than the sum, over the days that can still be planted,
    of ``(turns + 1) // 3`` must leave seeds unplanted, which the scheduler
    rejects. It is not an estimate of what will fit.
    """
    spawn = tuple(spawn_position(game_state.player.farm))
    last_day = LAST_ACTION_STEP // TURNS_PER_DAY
    total = 0
    for day in range(game_state.day, last_day + 1):
        sprout = PlantTile(TOMATO, day, False, 1, 0, -1, -1)
        if tomato_harvest_day(sprout, spawn, spawn) is None:
            break
        if day == game_state.day:
            turns = turns_left_today(game_state)
        else:
            turns = min(TURNS_PER_DAY, LAST_ACTION_STEP + 1 - day * TURNS_PER_DAY)
        total += (turns + 1) // 3
    return total


def last_planting_day(game_state: GameState) -> int:
    """Return the last day a tomato could still be planted usefully, from ``game_state``'s day on.

    Planting on the spawn tile is the easiest case (distance 0); farther
    tiles and later days are only harder. Earlier than the current day if
    no day is left.
    """
    spawn = tuple(spawn_position(game_state.player.farm))
    for day in range(LAST_ACTION_STEP // TURNS_PER_DAY, game_state.day - 1, -1):
        if tomato_harvest_day(PlantTile(TOMATO, day, False, 1, 0, -1, -1), spawn, spawn) is not None:
            return day
    return game_state.day - 1


def remaining_tomatoes_cannot_be_planted(
    game_state: GameState, remaining: int, exempt: Set[Tile] = frozenset()
) -> bool:
    """Return True only if no schedule can plant ``remaining`` more tomatoes usefully.

    A necessary condition, used to reject an impossible wave early instead
    of simulating it until its seeds go to waste. False means only that
    the condition did not rule the wave out.

    It applies when every tomato planted from today on stays alive, with a
    care job every day, through the last useful planting day, so the day
    ``D`` of the last planting is reached with all of them still on the
    farm. On ``D``, the scheduler's last construction check needs room for
    every job then due (done earlier that day, or still pending and costed
    in its tour) and the planting:

    - actions: one per known plant with a certain job on ``D``, one water
      per remaining tomato planted before ``D``, and a PLANT and WATER per
      tomato planted on ``D`` (at least one): at least
      ``len(K) + remaining + 1``;
    - moves: a walk from the day's start visiting every such tile, which is
      at least the minimum spanning tree of the start and those tiles.

    The remaining tomatoes can only go on the first ``remaining`` tiles of
    ``planting_order`` (the scheduler plants nowhere else), so their tiles
    are known. Known plants count only while their job is certain: an
    unfertilized tomato through its harvest day, a fertilized one up to the
    day before it. Living wheat could free its tile and change where
    tomatoes go, so with wheat on the farm the condition is not applied.
    """
    if remaining <= 0:
        return False
    farm = game_state.player.farm
    spawn = tuple(spawn_position(farm))
    last = last_planting_day(game_state)
    plots = planting_order(game_state)
    if last < game_state.day or len(plots) < remaining:
        return True
    known = []
    for y, row in enumerate(farm.tiles):
        for x, tile in enumerate(row):
            if not isinstance(tile, PlantTile) or (x, y) in exempt:
                continue
            if tile.crop == WHEAT:
                return False
            if tile.crop != TOMATO or not has_value(tile, (x, y), game_state):
                continue
            harvest_day = tomato_harvest_day(tile, (x, y), spawn)
            if harvest_day is None:
                continue
            certain_until = harvest_day if tile.fertilized_until_day < 0 else harvest_day - 1
            if certain_until >= last:
                known.append((x, y))
    # Every tomato planted from today on must have a certain job through `last`.
    earliest_harvest = min(
        (tomato_harvest_day(PlantTile(TOMATO, game_state.day, False, 1, 0, -1, -1), p, spawn) for p in plots),
        default=None,
        key=lambda d: -1 if d is None else d,
    )
    if earliest_harvest is None or earliest_harvest < last:
        return False
    tiles = plots[:remaining]
    if game_state.day < last:
        later = len(known) + remaining + 1 + _spanning_tree([spawn, *known, *tiles])
        if later <= min(TURNS_PER_DAY, LAST_ACTION_STEP + 1 - last * TURNS_PER_DAY):
            return False
    pending = sorted({job.tile for job in care_jobs(game_state)} - set(exempt))
    today = len(pending) + remaining + 1 + _spanning_tree(
        [tuple(farm.farmer), *pending, *tiles]
    )
    return today > turns_left_today(game_state)


def _spanning_tree(points: Sequence[Tile]) -> int:
    """Return the length of a minimum spanning tree of ``points`` (Manhattan distance)."""
    points = list(dict.fromkeys(tuple(p) for p in points))
    if len(points) < 2:
        return 0
    nearest = {p: _distance(points[0], p) for p in points[1:]}
    total = 0
    while nearest:
        point = min(nearest, key=nearest.get)
        total += nearest.pop(point)
        for other in nearest:
            d = _distance(point, other)
            if d < nearest[other]:
                nearest[other] = d
    return total


def _distance(a: Sequence[int], b: Sequence[int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _step_toward(position: Sequence[int], target: Tile) -> Action:
    x, y = position
    tx, ty = target
    if x != tx:
        return Action(EAST if tx > x else WEST)
    return Action(SOUTH if ty > y else NORTH)


def _new_plant_is_useful(crop: str, tile: Tile, game_state: GameState) -> bool:
    """Return whether ``crop`` planted on ``tile`` today could still produce something sellable."""
    day = game_state.day
    spawn = spawn_position(game_state.player.farm)
    if crop == TOMATO:
        sprout = PlantTile(TOMATO, day, False, 1, 0, -1, -1)
        return tomato_harvest_day(sprout, tile, spawn) is not None
    # Wheat is first harvestable first_yield_day days after planting.
    harvest_step = (day + CROPS[crop].first_yield_day) * TURNS_PER_DAY
    return harvest_step + 2 * _distance(spawn, tile) + 1 <= LAST_ACTION_STEP


# --- realizing a hypothesis ---------------------------------------------


class _Run:
    """Builds one schedule turn by turn, playing each turn on the Simulator."""

    def __init__(self, simulator: Simulator, game_state: GameState, hypothesis: Hypothesis):
        self._simulator = simulator
        self._state = game_state
        self._hypothesis = hypothesis
        self._turns: list[Turn] = []
        self._targets = set(hypothesis.targets)
        crop = hypothesis.crop
        held = game_state.player.seeds.get(crop, 0) if crop else 0
        # Seeds held beyond the hypothesis's plantings are left unplanted.
        self._reserve = held + hypothesis.buy - hypothesis.plant
        if self._reserve < 0:
            raise ValueError("The hypothesis plants more seeds than it holds or buys")
        self._exempt = unsavable_plants(game_state)

    def run(self) -> Schedule | None:
        checked_day = None
        while True:
            if self._state.step > LAST_ACTION_STEP:
                return None
            if self._state.day != checked_day and self._hypothesis.crop == TOMATO:
                checked_day = self._state.day
                if remaining_tomatoes_cannot_be_planted(self._state, self._seeds_to_plant(), self._exempt):
                    raise ValueError("The TOMATO seeds can no longer all be planted usefully")
            jobs = care_jobs(self._state)
            urgent = [j for j in jobs if j.priority <= VALUE]
            if self._finished() and (not urgent or self._only_time_to_liquidate()):
                return self._liquidate()
            construction = self._construction_job(jobs)
            candidates = jobs + ([construction] if construction else [])
            position = self._state.player.farm.farmer
            farmer = None
            if candidates:
                job = min(candidates, key=lambda j: j.order(position))
                if tuple(position) != job.tile:
                    farmer = _step_toward(position, job.tile)
                elif job.action == PLANT:
                    # A seed bought this turn arrives only after the farmer acts.
                    crop = self._hypothesis.crop
                    if self._state.player.seeds.get(crop, 0) > 0:
                        farmer = Action(PLANT, crop)
                else:
                    farmer = Action(job.action)
            self._play(farmer, self._first_orders())
            if farmer is not None and farmer.action_type == PLANT:
                self._targets.add(tuple(position))

    def _first_orders(self) -> tuple[Action, ...]:
        hypothesis = self._hypothesis
        if self._turns or not hypothesis.buy:
            return ()
        return (Action(BUY_SEED, hypothesis.crop, hypothesis.buy),)

    def _seeds_to_plant(self) -> int:
        """Seeds still to plant: those held, plus those bought this turn, beyond the reserve."""
        crop = self._hypothesis.crop
        if crop is None:
            return 0
        held = self._state.player.seeds.get(crop, 0)
        arriving = self._hypothesis.buy if not self._turns else 0
        return max(0, held + arriving - self._reserve)

    def _construction_job(self, jobs: list[Job]) -> Job | None:
        """Return the next planting the day can still fit, or None.

        Raises:
            ValueError: If seeds remain to plant but none can be planted
                usefully any more.
        """
        remaining = self._seeds_to_plant()
        if remaining == 0:
            return None
        crop = self._hypothesis.crop
        plots = planting_order(self._state)[:remaining]
        if len(plots) < remaining or not _new_plant_is_useful(crop, plots[-1], self._state):
            raise ValueError(f"The {crop} seeds can no longer all be planted usefully")
        position = self._state.player.farm.farmer
        left = turns_left_today(self._state)
        others = [j.tile for j in jobs]
        # Each other job is on its own tile, never the empty plot, so the
        # tour costs at least a move and an action per job.
        least_tour = 2 * len(set(others))
        for plot in sorted(plots, key=lambda p: (_distance(position, p), p[1], p[0])):
            walk = _distance(position, plot)
            if walk + 2 + least_tour > left:
                break  # Plots are in distance order: no later plot can fit either.
            cost = walk + 2 + tour_cost(plot, [t for t in others if t != plot])
            if cost <= left:
                return Job(CONSTRUCTION, plot, PLANT)
        return None

    def _finished(self) -> bool:
        """Whether every planting is done and every target has had its last harvest."""
        if self._seeds_to_plant() > 0:
            return False
        tiles = self._state.player.farm.tiles
        for x, y in self._targets:
            plant = tiles[y][x]
            if isinstance(plant, PlantTile) and has_value(plant, (x, y), self._state):
                return False
        return True

    def _only_time_to_liquidate(self) -> bool:
        """Whether the season leaves no turn beyond those the final sale needs.

        Then the sale comes first: any other work could no longer be sold.
        """
        spawn = spawn_position(self._state.player.farm)
        needed = _distance(self._state.player.farm.farmer, spawn) + 1 if self._carrying() else 1
        return LAST_ACTION_STEP + 1 - self._state.step <= needed

    def _liquidate(self) -> Schedule | None:
        """Drop carried crops at the spawn tile and sell every WHEAT and TOMATO in one turn."""
        spawn = tuple(spawn_position(self._state.player.farm))
        while self._carrying() and tuple(self._state.player.farm.farmer) != spawn:
            self._play(_step_toward(self._state.player.farm.farmer, spawn), ())
        carried = carried_items(self._state.player, FARMER) if self._carrying() else {}
        shed = self._state.player.inventory.items
        sales = tuple(
            Action(SELL, crop, shed.get(crop, 0) + carried.get(crop, 0))
            for crop in MANAGED_CROPS
            if shed.get(crop, 0) + carried.get(crop, 0) > 0
        )
        if not sales:
            raise ValueError("Nothing to sell")
        self._play(Action(DROP) if carried else None, sales)
        return Schedule(tuple(self._turns), self._state)

    def _carrying(self) -> bool:
        carried = carried_items(self._state.player, FARMER)
        return any(carried.get(crop, 0) > 0 for crop in MANAGED_CROPS)

    def _play(self, farmer: Action | None, market: tuple[Action, ...]) -> None:
        """Play one turn, and reject the schedule if a maintainable plant with value dies.

        Raises:
            ValueError: If the turn cannot be simulated, is past the
                season's last action, or loses a plant it should not.
        """
        before = self._state
        if before.step > LAST_ACTION_STEP:
            raise ValueError("Past the season's last action")
        turn = Turn(farmer=farmer, market=market)
        self._state = self._simulator.play_turn(before, turn, isolated=False)
        self._turns.append(turn)
        tiles_after = self._state.player.farm.tiles
        # Simulation is copy-on-write: a grid it did not change is the same
        # object, and an unchanged grid cannot have lost a plant.
        if tiles_after is before.player.farm.tiles:
            return
        for y, row in enumerate(before.player.farm.tiles):
            for x, plant in enumerate(row):
                if (
                    isinstance(plant, PlantTile)
                    and plant.crop in MANAGED_CROPS
                    and isinstance(tiles_after[y][x], WeedTile)
                    and (x, y) not in self._exempt
                    and has_value(plant, (x, y), before)
                ):
                    raise ValueError(f"The {plant.crop} on {(x, y)} was lost")
