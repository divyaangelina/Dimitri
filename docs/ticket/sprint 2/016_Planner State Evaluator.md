Ticket #016 — Planner State Evaluator

We are continuing Dimitri's architecture.

Goal:
Create the Planner's Evaluator layer.

Architecture:

FACTS → INFERENCES → CANDIDATE FUTURES → EVALUATION → DECISION

The Analyst describes the current state.
The CandidateGenerator produces possible actions.
The Simulator produces hypothetical states.
The Evaluator assigns a deterministic score to a hypothetical state.
The Executive will eventually compare candidates and choose an action.

IMPORTANT:
The Evaluator scores STATES, not actions.

It must NOT choose a winner.

Read the existing implementation and tests before changing anything.
Preserve the current architecture. Do not perform unrelated refactors.

==================================================
1. CREATE EVALUATION MODEL
==================================================

Create:

dimitri/planner/evaluation.py

Define an immutable dataclass:

@dataclass(frozen=True)
class Evaluation:
    cash: int
    inventory_value: int
    seed_cost: int
    total_liquid_value: int

Definitions:

cash:
    Player's current money.

inventory_value:
    Total theoretical sale value of the player's inventory using current
    market prices.

seed_cost:
    Total theoretical replacement cost of currently held seeds using
    current market prices.

total_liquid_value:
    cash + inventory_value

IMPORTANT:

Do NOT subtract seed_cost from total_liquid_value.

Seed cost is reported separately because seeds are an existing asset/
resource, not a debt.

Do NOT call total_liquid_value "profit", "ROI", or "expected value".

==================================================
2. CREATE EVALUATOR
==================================================

Create:

dimitri/planner/evaluator.py

Define:

class Evaluator:
    def evaluate(self, game_state: GameState) -> Evaluation:
        ...

The Evaluator should calculate the same accounting quantities established
by Analyst Ticket #011.

Use current GameState data directly or reuse a small existing deterministic
calculation helper if one already exists.

Do NOT make Evaluator depend on Analyst state.

The Evaluator must be independently usable on any valid GameState.

==================================================
3. INVENTORY VALUATION
==================================================

inventory_value:

For every item in player.inventory:

    quantity * current market price

Only items with a corresponding market price contribute.

Unknown inventory items must not crash evaluation.

==================================================
4. SEED VALUATION
==================================================

seed_cost:

For every seed in player.seeds:

    quantity * current market price

Only seeds with a corresponding market price contribute.

Unknown seed types must not crash evaluation.

==================================================
5. NO DECISION MAKING
==================================================

Evaluator must NOT:

- choose an action
- rank actions
- compare multiple actions
- declare a winner
- recommend buying
- recommend selling
- recommend planting
- calculate ROI
- predict future prices
- simulate future states
- inspect opponent strategy
- create plans

For example, this is valid:

    Evaluation(
        cash=1000,
        inventory_value=500,
        seed_cost=200,
        total_liquid_value=1500,
    )

This is NOT valid:

    "BUY_TOMATO_SCORE = 1500"
    "TOMATO IS BEST"
    "ACTION_SCORE = ..."

The Evaluator only answers:

"What is this state worth under our current accounting model?"

==================================================
6. IMMUTABILITY
==================================================

Evaluation must be frozen/immutable.

Evaluator.evaluate() must not mutate GameState or any nested structure.

==================================================
7. TESTS
==================================================

Create:

tests/test_planner_evaluator.py

Test at minimum:

1. cash is calculated correctly.
2. inventory_value is calculated correctly.
3. seed_cost is calculated correctly.
4. total_liquid_value equals cash + inventory_value.
5. unknown inventory items do not crash evaluation.
6. unknown seed types do not crash evaluation.
7. Evaluation is immutable.
8. Evaluating a GameState does not mutate it.
9. Two identical GameStates produce identical Evaluations.
10. Different cash values produce corresponding evaluation changes.
11. Different inventory values produce corresponding evaluation changes.
12. Different seed values change seed_cost without changing total_liquid_value.
13. Existing full test suite still passes.

Use existing test fixtures/helpers wherever possible.

==================================================
8. ARCHITECTURAL CONSISTENCY
==================================================

The Analyst and Evaluator may calculate related accounting quantities,
but do not introduce unnecessary abstraction merely to eliminate a few
lines of arithmetic.

Prefer simple, readable code.

Do not create:

- ScoringEngine
- ValueEngine
- EconomicEngine
- DecisionEngine
- RankingEngine
- StrategyEngine

Do not modify Observer, Parser, Validator, Farm, Opponent, or Executive
unless a genuine compatibility issue requires it.

==================================================
9. VALIDATION
==================================================

Run:

python -m pytest -v

All existing and new tests must pass.

At the end, report:

- files created/changed
- what was implemented
- total test count
- test result
- any assumptions or compatibility issues discovered

Do not make unrelated changes.