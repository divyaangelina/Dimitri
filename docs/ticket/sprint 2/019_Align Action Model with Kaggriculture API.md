Ticket #019 — Align Internal Action Model with Kaggriculture API

Context:
Dimitri's internal action model currently uses a generic BUY action, but the actual Kaggriculture API has distinct market actions:
- BUY_SEED
- BUY_ANIMAL
- BUY_PRODUCT
- SELL
- HIRE
- BUY_LAND

Farmer actions and market actions are submitted separately:
{
    "farmer": [...],
    "hands": [...],
    "market": [...]
}

The official competition specification also confirms:
- BUY_SEED buys seeds
- BUY_ANIMAL buys animals
- BUY_PRODUCT buys products such as wheat/fertilizer
- SELL sells an item
- HIRE hires a farm hand
- BUY_LAND unlocks a land quadrant

Task:
1. Inspect the current action-related code and tests.
2. Replace the generic internal BUY representation with explicit action types that distinguish:
   - BUY_SEED
   - BUY_ANIMAL
   - BUY_PRODUCT
   - SELL
   - HIRE
   - BUY_LAND
3. Preserve the separation between farmer actions, hand actions, and market actions.
4. Update any affected Generator, Simulator, Planner, or action model code and tests.
5. Do NOT implement Operator execution yet.
6. Do NOT add strategy, ROI calculations, rankings, or decision logic.
7. Keep the architecture simple and consistent with our existing principles:
   - models represent facts/data
   - analyst derives facts
   - planner generates/evaluates possibilities
   - executive chooses
   - operator executes
8. Do not perform unrelated refactors.

Important:
Use the actual Kaggriculture action names exactly as documented. Do not invent a generic BUY abstraction.

Run:
python -m pytest -v

All existing tests plus the new/updated tests must pass.
