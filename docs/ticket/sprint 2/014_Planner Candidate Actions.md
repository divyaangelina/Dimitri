Ticket #014 — Planner Candidate Actions

We are continuing Dimitri's architecture.

Goal:
Create the Planner's candidate-action layer.

Architecture:

FACTS → INFERENCES → CANDIDATE FUTURES → DECISIONS

The Analyst describes the current state.
The Planner considers possible actions.
The Executive will eventually choose and commit to an action.

For this ticket, the Planner must ONLY represent and generate valid candidate
actions from the current GameState.

It must NOT choose the best action yet.

Read the existing implementation and tests before making changes.
Preserve the current architecture. Do not perform unrelated refactors.

==================================================
1. CREATE ACTION MODEL
==================================================

Create:

dimitri/planner/action.py

Define an immutable dataclass:

@dataclass(frozen=True)
class Action:
    action_type: str
    target: str | None = None
    quantity: int = 1

The model represents one possible game action.

Examples:

Action(action_type="BUY", target="WHEAT", quantity=1)
Action(action_type="SELL", target="EGG", quantity=2)
Action(action_type="PLANT", target="TOMATO", quantity=1)

Do NOT add game-specific execution logic to Action.

Action is a representation only.

==================================================
2. CREATE CANDIDATE GENERATOR
==================================================

Create:

dimitri/planner/generator.py

Define:

class CandidateGenerator:
    def generate(self, game_state: GameState) -> tuple[Action, ...]:
        ...

For this first version, generate only actions that can be established
directly from the currently observable state.

Generate:

A. BUY actions

For every item in GameState.market.prices that Dimitri can currently
afford, generate:

Action(
    action_type="BUY",
    target=item,
    quantity=1
)

Use:

market price <= player money

Do not generate quantities greater than 1 yet.

B. SELL actions

For every item currently present in Dimitri's inventory with quantity > 0,
generate:

Action(
    action_type="SELL",
    target=item,
    quantity=1
)

Only generate SELL actions for items that have a current market price.

C. PLANT actions

For every crop seed Dimitri currently owns with quantity > 0, generate:

Action(
    action_type="PLANT",
    target=crop,
    quantity=1
)

Do NOT generate animal, fertilizer, hire, expansion, or other actions yet.

Those will be added in later tickets when the underlying action semantics
are properly modeled.

==================================================
3. NO DECISION MAKING
==================================================

CandidateGenerator must NOT:

- rank actions
- score actions
- choose an action
- recommend an action
- calculate ROI
- calculate expected profit
- predict future prices
- simulate future states
- inspect opponent strategy
- create a plan

If there are 8 valid actions, return all 8.

The Planner is considering possibilities, not selecting one.

==================================================
4. ORDERING
==================================================

Make candidate generation deterministic.

Use this ordering:

1. BUY actions
2. SELL actions
3. PLANT actions

Within each category, preserve the ordering of the underlying mapping
from the GameState.

Do not sort alphabetically unless the existing data structure already
provides that order.

==================================================
5. TESTS
==================================================

Create:

tests/test_planner_generator.py

Test at minimum:

1. Affordable market items generate BUY actions.
2. Items more expensive than current money do not generate BUY actions.
3. An item exactly equal to current money generates a BUY action.
4. Inventory items with quantity > 0 generate SELL actions.
5. Inventory items with quantity == 0 do not generate SELL actions.
6. Inventory items without a market price do not generate SELL actions.
7. Seeds with quantity > 0 generate PLANT actions.
8. Seeds with quantity == 0 do not generate PLANT actions.
9. BUY actions appear before SELL actions.
10. SELL actions appear before PLANT actions.
11. Mapping order is preserved within each category.
12. Every generated action has quantity == 1.
13. Candidate generation is deterministic.
14. Candidate generation does not mutate GameState.
15. Action instances are immutable.
16. Existing full test suite still passes.

==================================================
6. KEEP THE ARCHITECTURE SIMPLE
==================================================

Do not create:

- StrategyEngine
- DecisionEngine
- ScoringEngine
- RankingEngine
- SimulationEngine
- EconomicOptimizer
- RecommendationEngine

Do not modify the Analyst's responsibilities.

Do not modify Observer, Parser, Validator, Farm, Opponent, Market, or
Executive unless a genuine compatibility issue requires it.

==================================================
7. VALIDATION
==================================================

Run:

python -m pytest -v

All existing and new tests must pass.

At the end, report:

- files created/changed
- what was implemented
- total test count
- test result

Do not make unrelated changes.