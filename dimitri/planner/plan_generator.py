"""Constructs concrete Plans for an Opportunity.

A PlanGenerator answers one question: can a valid concrete plan for this
opportunity be built from this GameState, and what are its turns? It
sits between Opportunity and Plan:

    Opportunity  what could we pursue?
        -> PlanGenerator  which concrete turns would pursue it?
        -> Plan
        -> PlanEvaluator  what economic state would it leave us in?

Plan generation constructs hypotheses. It does not determine whether a
hypothesis is desirable: a generator never evaluates, scores, ranks, or
compares plans, and never decides whether an opportunity is worth
pursuing. It only returns plans that the Simulator can play from the
given state.

A generator that already simulated a plan while building it can hand
that result on through ``generate_with_states``, so callers such as the
ContinuationEvaluator need not simulate the same plan again.

WHEAT_PRODUCTION and TOMATO_PRODUCTION have concrete generators. A generator
decides only which economic hypothesis to test, starting from the observed
state, including any investment already under way. The shared FarmScheduler
realizes it while keeping the rest of the farm alive.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from dimitri.analyst.opportunity import Opportunity, OpportunityKind
from dimitri.models.game_state import GameState
from dimitri.planner.farm_scheduler import (
    TOMATO,
    WHEAT,
    FarmScheduler,
    Hypothesis,
    has_value,
    living_plants,
    max_tomato_plantings,
    planting_order,
    production_days,
    unsavable_plants,
)
from dimitri.planner.plan import Plan
from dimitri.planner.rules import FARMER, carried_items
from dimitri.planner.simulator import Simulator
from dimitri.utils.constants import CROPS

__all__ = [
    "GeneratedPlan",
    "PlanGenerator",
    "TomatoPlanGenerator",
    "WheatPlanGenerator",
    "tomato_program_limit",
    "living_plants",
    "living_wheat",
    "production_days",
]


@dataclass(frozen=True)
class GeneratedPlan:
    """A generated Plan, with the state it leaves if the generator already knows it.

    Attributes:
        plan: The generated Plan.
        resulting_state: Exactly ``Simulator.simulate_plan(game_state,
            plan)`` from the state the plan was generated for, when the
            generator simulated the plan while building it; otherwise
            None, and a caller that needs it must simulate the plan.
    """

    plan: Plan
    resulting_state: GameState | None = None


class PlanGenerator(ABC):
    """Builds concrete Plans for one kind of Opportunity."""

    opportunity_kind: OpportunityKind

    @abstractmethod
    def generate(self, game_state: GameState, opportunity: Opportunity) -> tuple[Plan, ...]:
        """Return the plans this generator can build for ``opportunity`` from ``game_state``.

        Returns an empty tuple when ``opportunity`` is not this
        generator's kind or no valid plan can be built. Every returned
        plan can be played by ``Simulator.simulate_plan`` from
        ``game_state``. ``game_state`` is never mutated.
        """

    def generate_with_states(
        self, game_state: GameState, opportunity: Opportunity
    ) -> tuple[GeneratedPlan, ...]:
        """Return ``generate``'s plans, each with its resulting state when already known.

        The default attaches no state. A generator that simulates its
        plans while building them overrides this to hand that result on.
        """
        return tuple(GeneratedPlan(plan) for plan in self.generate(game_state, opportunity))


class _ScheduledPlanGenerator(PlanGenerator):
    """A generator whose hypotheses are realized by the shared FarmScheduler.

    The generator decides only *what* economic hypothesis to test; the
    FarmScheduler realizes it while keeping every maintainable plant
    already on the farm alive and selling its output. The plan's
    opportunity is the incremental hypothesis; care for other plants is
    background work, not another opportunity.
    """

    def __init__(self, simulator: Simulator | None = None):
        self._simulator = simulator if simulator is not None else Simulator()
        self._scheduler = FarmScheduler(self._simulator)

    def generate(self, game_state: GameState, opportunity: Opportunity) -> tuple[Plan, ...]:
        return tuple(g.plan for g in self.generate_with_states(game_state, opportunity))

    def _realize(
        self,
        game_state: GameState,
        opportunity: Opportunity,
        hypothesis: Hypothesis,
        label: str,
    ) -> GeneratedPlan | None:
        """Return the plan realizing ``hypothesis``, with its isolated state, or None."""
        schedule = self._scheduler.schedule(game_state, hypothesis)
        if schedule is None:
            return None
        plan = Plan(opportunity, turns=schedule.turns, horizon=len(schedule.turns), label=label)
        return GeneratedPlan(plan, self._simulator.isolate(schedule.state))


class WheatPlanGenerator(_ScheduledPlanGenerator):
    """Builds one WHEAT_PRODUCTION plan from the current state: continue or start one wheat.

    The hypothesis is, in this order of precedence:

    1. **Continue a living wheat plant.** Living wheat plants that can be
       kept alive are tried oldest first (earliest ``planted_day``), ties
       broken by row, then column; the first that can be harvested and
       sold by the season's last action is the plan's target.
    2. **Sell held wheat** the farmer carries or the shed holds.
    3. **Start one wheat** on the empty tile nearest the spawn tile,
       planting a held seed, or buying one first if none is held.

    The FarmScheduler realizes it, keeping every other maintainable
    WHEAT and TOMATO plant alive, and ends once the wheat is sold. No
    plan is returned when the hypothesis cannot be realized that way.
    """

    opportunity_kind = OpportunityKind.WHEAT_PRODUCTION

    def generate_with_states(
        self, game_state: GameState, opportunity: Opportunity
    ) -> tuple[GeneratedPlan, ...]:
        if opportunity.kind is not self.opportunity_kind:
            return ()
        unsavable = unsavable_plants(game_state)
        for plot in living_plants(game_state, WHEAT):
            if plot in unsavable:
                continue
            generated = self._realize(
                game_state, opportunity, Hypothesis(targets=(plot,)), f"continue WHEAT at {plot}"
            )
            if generated is not None:
                return (generated,)
        if _holds(game_state, WHEAT):
            generated = self._realize(game_state, opportunity, Hypothesis(), "sell WHEAT")
            return () if generated is None else (generated,)
        plots = planting_order(game_state)
        if not plots:
            return ()
        buy = 0 if game_state.player.seeds.get(WHEAT, 0) > 0 else 1
        generated = self._realize(
            game_state, opportunity, Hypothesis(WHEAT, plant=1, buy=buy), f"WHEAT at {plots[0]}"
        )
        return () if generated is None else (generated,)


class TomatoPlanGenerator(_ScheduledPlanGenerator):
    """Builds one TOMATO_PRODUCTION plan from the current state: continue or start a program.

    Tomato is an ongoing crop: one plant produces a unit at the end of
    several consecutive days, harvesting does not remove it, and its yield
    accumulates on the plant. The hypothesis is a tomato *program*: the
    largest number of tomatoes the FarmScheduler can plant and sell over
    the rest of the season. That is not limited to what can be cared for at
    once: a program may plant one run, wait for its harvest to free the
    farmer's day, and plant another. In order of precedence:

    1. **Continue the existing program**: every living tomato that can be
       kept alive and still has value, together with the held tomato
       seeds, which are its unplanted remainder.
    2. **Plant the held tomato seeds** as a program, buying none.
    3. **Sell held tomatoes** the farmer carries or the shed holds.
    4. **Start a fresh program**: buy and plant ``k`` tomatoes, at most
       ``tomato_program_limit`` (money and empty tiles).

    Held tomato seeds cannot be told apart from seeds bought for any other
    reason, so every held tomato seed is treated as part of the program,
    and the program's final sale sells every tomato in the shed. So a
    replan from any point of a program continues that same program.

    The number of new plants starts at the limit and is reduced one at a
    time until the scheduler accepts it; feasibility is not monotonic in
    that number, so none is skipped except those an exact necessary
    condition rules out (``max_tomato_plantings``). That search is
    mechanical feasibility, not economic branching: at most one tomato
    plan is ever returned. **The largest feasible program is not claimed
    to be economically optimal**: it matched the best tested size in 19 of
    20 audited states (ticket #051), and from a fresh day-8 state a
    16-tomato program ends about $100 better than the largest, 18.

    Each plant is watered daily and harvested once on the day after its
    last useful production (see FarmScheduler). The plan ends once every
    plant of the hypothesis has been harvested for the last time and its
    tomatoes sold. Fertilizer is never applied.
    """

    opportunity_kind = OpportunityKind.TOMATO_PRODUCTION

    def generate_with_states(
        self, game_state: GameState, opportunity: Opportunity
    ) -> tuple[GeneratedPlan, ...]:
        if opportunity.kind is not self.opportunity_kind:
            return ()
        held = game_state.player.seeds.get(TOMATO, 0)
        plots = planting_order(game_state)
        unsavable = unsavable_plants(game_state)
        tiles = game_state.player.farm.tiles
        living = tuple(
            (x, y)
            for x, y in living_plants(game_state, TOMATO)
            if (x, y) not in unsavable and has_value(tiles[y][x], (x, y), game_state)
        )
        if living:
            # Larger plantings could not all be planted usefully (exact bound).
            most = min(held, len(plots), max_tomato_plantings(game_state))
            for plant in range(most, -1, -1):
                total = len(living) + plant
                label = (
                    f"continue TOMATO at {living[0]}"
                    if total == 1
                    else f"continue TOMATO wave of {total}"
                )
                hypothesis = Hypothesis(TOMATO, plant=plant, targets=living)
                generated = self._realize(game_state, opportunity, hypothesis, label)
                if generated is not None:
                    return (generated,)
        limit = min(tomato_program_limit(game_state), max_tomato_plantings(game_state))
        if held:
            # Held seeds are the unfinished program: plant them, buying none.
            generated = self._largest_program(game_state, opportunity, limit, buy=False)
            if generated is not None:
                return (generated,)
        if _holds(game_state, TOMATO):
            generated = self._realize(game_state, opportunity, Hypothesis(), "sell TOMATO")
            return () if generated is None else (generated,)
        if held:
            return ()
        generated = self._largest_program(game_state, opportunity, limit, buy=True)
        return () if generated is None else (generated,)

    def _largest_program(
        self, game_state: GameState, opportunity: Opportunity, limit: int, *, buy: bool
    ) -> GeneratedPlan | None:
        """Return the largest program of at most ``limit`` tomatoes the scheduler accepts.

        Feasibility is not monotonic in the size, so every size is tried,
        largest first, and the first accepted is kept.
        """
        plots = planting_order(game_state)
        for size in range(limit, 0, -1):
            label = f"TOMATO at {plots[0]}" if size == 1 else f"TOMATO wave of {size}"
            hypothesis = Hypothesis(TOMATO, plant=size, buy=size if buy else 0)
            generated = self._realize(game_state, opportunity, hypothesis, label)
            if generated is not None:
                return generated
        return None


def tomato_program_limit(game_state: GameState) -> int:
    """Return the most tomatoes a program from ``game_state`` could request.

    The held tomato seeds if any are held (they are the unfinished program,
    and none are bought); otherwise as many seeds as the bank can buy.
    Never more than the empty unlocked tiles: a tomato leaves a weed, so a
    tile is planted at most once. Whether that many can actually be planted
    and sold is left to the FarmScheduler.
    """
    held = game_state.player.seeds.get(TOMATO, 0)
    seeds = held if held else int(game_state.player.money // CROPS[TOMATO].seed_price)
    return min(seeds, len(planting_order(game_state)))


def living_wheat(game_state: GameState) -> list[tuple[int, int]]:
    """Return the ``(x, y)`` of every living wheat plant, oldest first (see ``living_plants``)."""
    return living_plants(game_state, WHEAT)


def _holds(game_state: GameState, crop: str) -> bool:
    """Return whether the farmer carries ``crop`` or the shed holds any."""
    player = game_state.player
    return (
        carried_items(player, FARMER).get(crop, 0) > 0
        or player.inventory.items.get(crop, 0) > 0
    )
