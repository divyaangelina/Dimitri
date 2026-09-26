Ticket #012 — Analyst Economic Opportunities

We are continuing Dimitri's architecture.

Goal:
Extend the Analyst so it can derive deterministic economic opportunity facts from the current GameState.

Architecture rule:

FACTS → INFERENCES → DECISIONS

Ticket #011 established accounting facts:
- current money
- market prices
- market inventory
- inventory total value
- seed total cost

Now derive simple opportunity metrics that downstream planning can use.

The Analyst must NOT choose actions.

==================================================
1. ADD OPPORTUNITY DATA MODEL
==================================================

Create:

dimitri/analyst/opportunity.py

Define an immutable dataclass:

@dataclass(frozen=True)
class EconomicOpportunity:
    item: str
    buy_cost: int
    sell_price: int
    gross_margin: int

Definitions:

buy_cost:
The current market price of one unit of the item.

sell_price:
For this game, use the same current market price.

gross_margin:
sell_price - buy_cost.

IMPORTANT:
This ticket is intentionally simple.

Because the current GameState only exposes one market price per item, the gross margin will normally be zero.

Do NOT invent separate buy/sell prices.

This model exists to establish the structure that future market data can support.

==================================================
2. EXTEND ANALYSIS
==================================================

Update:

dimitri/analyst/analysis.py

Add:

economic_opportunities: tuple[EconomicOpportunity, ...]

The tuple should contain one opportunity for each item present in
GameState.market.prices.

Keep the Analysis immutable.

==================================================
3. UPDATE ANALYST
==================================================

Update:

dimitri/analyst/analyst.py

Create one EconomicOpportunity for every market item.

For each item:

buy_cost = current market price
sell_price = current market price
gross_margin = sell_price - buy_cost

Preserve deterministic ordering from the market price mapping.

Do NOT:
- rank opportunities
- select the best opportunity
- recommend what Dimitri should buy
- recommend what Dimitri should sell
- calculate ROI
- calculate expected future profit
- predict prices
- inspect opponent strategy
- simulate future states

The Analyst is reporting opportunity facts only.

==================================================
4. TESTS
==================================================

Update:

tests/test_analyst.py

Add tests for:

1. Every market item produces exactly one EconomicOpportunity.
2. The item name is correct.
3. buy_cost equals the current market price.
4. sell_price equals the current market price.
5. gross_margin equals sell_price - buy_cost.
6. Opportunity ordering follows market price mapping order.
7. economic_opportunities is immutable through the frozen Analysis.
8. Changing the source market mapping after analysis does not change the Analysis.
9. Existing Analyst tests still pass.
10. GameState remains unchanged after analysis.

Use the existing test helpers/fixtures.

==================================================
5. KEEP THE ARCHITECTURE SIMPLE
==================================================

Do not create:
- OpportunityEngine
- MarketEngine
- PricingEngine
- StrategyEngine
- RankingEngine
- Recommendation classes
- Simulation code

Do not modify Observer, Parser, Validator, Farm, Opponent, or other unrelated modules.

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