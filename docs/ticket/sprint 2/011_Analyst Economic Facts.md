Ticket #011 — Analyst Economic Facts

We are continuing Dimitri's architecture.

Goal:
Extend the Analyst so it can derive deterministic economic facts from the current GameState.

Architecture rule:
FACTS → INFERENCES → DECISIONS

The Analyst may produce derived economic facts, but it must NOT choose actions, recommend crops/animals, rank investments, calculate "best" actions, simulate future states, or make decisions.

Read the existing code and tests before making changes. Preserve the current architecture and avoid unrelated refactors.

==================================================
1. EXTEND Analysis
==================================================

Update:

dimitri/analyst/analysis.py

Add these immutable fields:

- market_prices: Mapping[str, int]
- market_inventory: Mapping[str, int]
- inventory_total_value: int
- seed_total_cost: int

Definitions:

market_prices:
A snapshot of current market prices from GameState.market.prices.

market_inventory:
A snapshot of current market inventory from GameState.market.inventory.

inventory_total_value:
The total theoretical sale value of Dimitri's current shed inventory using current market prices.

For every item in player.inventory:
    quantity * current market price

Only items that have both an inventory quantity and a market price contribute to the total.

seed_total_cost:
The total theoretical replacement cost of Dimitri's currently held seeds using current market prices.

For every seed:
    seed quantity * current market price

Only crop seeds with a corresponding market price contribute.

IMPORTANT:
These are accounting facts only.
Do NOT call them profit, ROI, expected value, or recommendation.

==================================================
2. UPDATE Analyst
==================================================

Update:

dimitri/analyst/analyst.py

The Analyst should populate all four new fields.

Use the existing GameState, Player, Inventory, and Market models.

Do not mutate GameState, Player, Inventory, Market, or any nested mappings.

The returned Analysis must remain immutable.

Make defensive copies of market_prices and market_inventory if necessary so that mutating the original GameState mappings after analysis cannot mutate the Analysis.

Likewise, do not expose mutable references through the Analysis object.

==================================================
3. TYPE / MODEL RULES
==================================================

Keep the implementation simple.

Do not introduce:
- EconomicEngine
- PricingEngine
- ValuationEngine
- Strategy classes
- Crop recommendation systems
- Investment rankings
- ROI calculations
- Future simulations
- New model hierarchies

Do not modify the existing Farm, Opponent, Observer, Parser, or Validator unless a genuine compatibility issue requires it.

==================================================
4. TESTS
==================================================

Add tests to:

tests/test_analyst.py

Test at minimum:

1. Market prices are copied into Analysis.
2. Market inventory is copied into Analysis.
3. Inventory total value is calculated correctly.
4. Seed total cost is calculated correctly.
5. Unknown inventory items do not crash valuation.
6. Unknown seed types do not crash valuation.
7. Analysis remains immutable.
8. Mutating the source GameState mappings after analysis does not mutate the Analysis.
9. Existing Analyst behavior still works:
   - current day
   - current hour
   - days remaining
   - current money
   - tile counts
10. GameState remains unchanged after analysis.

Use the existing test fixtures/helpers where possible.

==================================================
5. VALIDATION
==================================================

Run:

python -m pytest -v

All existing tests and new tests must pass.

Do not make unrelated changes.

At the end, report:
- files changed
- what was implemented
- test count and result