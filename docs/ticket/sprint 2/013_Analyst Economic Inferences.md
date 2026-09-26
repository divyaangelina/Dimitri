Ticket #013 — Analyst Economic Inferences

We are continuing Dimitri's architecture.

Goal:
Extend the Analyst with deterministic economic inferences derived from the
facts already available in GameState and Analysis.

Architecture:

FACTS → INFERENCES → DECISIONS

The Analyst may derive useful interpretations of the current state, but it
must NOT select actions or create plans.

Read the existing implementation and tests before changing anything.
Preserve the current architecture. Do not perform unrelated refactors.

==================================================
1. EXTEND Analysis
==================================================

Update:

dimitri/analyst/analysis.py

Add these immutable fields:

- cash_plus_inventory_value: int
- cash_after_seed_replacement: int
- affordable_market_items: tuple[str, ...]
- has_empty_farm_capacity: bool

Definitions:

cash_plus_inventory_value:
    current_money + inventory_total_value

cash_after_seed_replacement:
    current_money - seed_total_cost

affordable_market_items:
    A tuple containing every item in market_prices whose current market
    price is less than or equal to current_money.

    Preserve the ordering of market_prices.

    This means:
        price <= current_money

    Do NOT rank the items.
    Do NOT recommend buying them.

has_empty_farm_capacity:
    True if empty_tiles > 0.
    False otherwise.

These are descriptive inferences about the current state.

==================================================
2. UPDATE Analyst
==================================================

Update:

dimitri/analyst/analyst.py

Populate all four fields.

Use values already calculated by Analyst rather than duplicating logic
unnecessarily.

For example:

cash_plus_inventory_value =
    current_money + inventory_total_value

cash_after_seed_replacement =
    current_money - seed_total_cost

affordable_market_items =
    tuple of market items whose price <= current_money

has_empty_farm_capacity =
    empty_tiles > 0

Do not mutate GameState or any nested object.

==================================================
3. IMPORTANT ARCHITECTURAL BOUNDARY
==================================================

The Analyst must NOT:

- choose the cheapest item
- choose the most expensive item
- choose the most profitable item
- recommend what to buy
- recommend what to plant
- recommend what to sell
- rank crops
- rank animals
- calculate ROI
- calculate expected future profit
- predict prices
- simulate future states
- create plans
- select actions

For example, this is allowed:

    affordable_market_items = ("WHEAT", "CARROT", "TOMATO")

This is NOT allowed:

    recommended_item = "TOMATO"

The Analyst describes the state.
The Planner will eventually reason about alternatives.

==================================================
4. TESTS
==================================================

Update:

tests/test_analyst.py

Add tests for:

1. cash_plus_inventory_value is calculated correctly.
2. cash_after_seed_replacement is calculated correctly.
3. affordable_market_items contains exactly the currently affordable items.
4. affordable_market_items preserves market price ordering.
5. An item priced exactly equal to current money is affordable.
6. An item priced above current money is not affordable.
7. has_empty_farm_capacity is True when at least one unlocked tile is empty.
8. has_empty_farm_capacity is False when no unlocked tiles are empty.
9. Analysis remains immutable.
10. Mutating source GameState mappings after analysis does not change the
    inferred values.
11. Existing Analyst tests continue to pass.
12. GameState remains unchanged after analysis.

Use the existing fixtures/helpers where possible.

==================================================
5. KEEP IT SIMPLE
==================================================

Do not create new engines, strategy classes, planners, ranking systems,
simulation systems, or recommendation systems.

Do not modify:

- Observer
- Parser
- Validator
- Farm
- Opponent
- Market

unless a genuine compatibility issue requires it.

==================================================
6. VALIDATION
==================================================

Run:

python -m pytest -v

All existing and new tests must pass.

At the end, report:

- files changed
- what was implemented
- total test count
- test result

Do not make unrelated changes.