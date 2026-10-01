Ticket #020 — Operator Foundation

Goal:
Build the first version of Dimitri's Operator layer.

Architecture:
The Operator executes decisions. It does NOT decide what action should be taken.

The responsibility boundaries are:

Observer
→ reads/parses Kaggriculture observations

Analyst
→ derives facts and metrics from GameState

Planner
→ generates and evaluates possible future actions/plans

Executive
→ selects the action/plan to commit to

Operator
→ executes the already-selected action through the Kaggriculture interface

Task:

1. Inspect the current architecture and existing action models after Ticket #019.

2. Implement the Operator foundation in:
   dimitri/operator/operator.py

3. The Operator should accept an already-decided action and convert it into the exact Kaggriculture action structure:

{
    "farmer": [...],
    "hands": [...],
    "market": [...]
}

4. The Operator must support the explicit market action types established in Ticket #019:
   - BUY_SEED
   - BUY_ANIMAL
   - BUY_PRODUCT
   - SELL
   - HIRE
   - BUY_LAND

5. Preserve the distinction between:
   - farmer actions
   - hand actions
   - market actions

6. The Operator must not:
   - choose actions
   - rank actions
   - calculate ROI
   - inspect opponent strategy
   - create plans
   - simulate outcomes
   - make economic decisions
   - modify GameState
   - contain farming strategy

7. Keep the first implementation intentionally small.
   We are building the execution boundary, not a complete game-playing agent yet.

8. Add focused unit tests for:
   - converting a farmer action
   - converting a hand action
   - converting each supported market action
   - producing the complete Kaggriculture action dictionary
   - rejecting malformed/unsupported actions where appropriate

9. Do not refactor unrelated code.

10. Run:

python -m pytest -v

All existing tests and new tests must pass.

Before making changes, inspect the existing action models and architecture so the implementation fits what is already there rather than creating duplicate abstractions.