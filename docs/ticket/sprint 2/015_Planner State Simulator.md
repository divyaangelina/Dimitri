Ticket #015 — Planner State Simulator

We are continuing Dimitri's architecture.

Goal:
Create the Planner's state simulation layer.

Architecture:

FACTS → INFERENCES → CANDIDATE FUTURES → DECISIONS

The Analyst describes the current state.
The CandidateGenerator produces possible actions.
The Simulator produces a hypothetical resulting state.
The Evaluator will eventually assess those futures.
The Executive will eventually choose an action.

For this ticket, the Simulator must ONLY apply the currently modeled,
directly observable effects of BUY, SELL, and PLANT actions.

Do not invent unobserved Kaggriculture mechanics.

Read the existing models, Analyst, Planner code, and tests before changing
anything.

==================================================
1. CREATE SIMULATOR
==================================================

Create:

dimitri/planner/simulator.py

Define:

class Simulator:
    def simulate(
        self,
        game_state: GameState,
        action: Action,
    ) -> GameState:
        ...

The method must return a NEW GameState.

It must NEVER mutate the original GameState.

==================================================
2. BUY SIMULATION
==================================================

For:

Action(action_type="BUY", target=item, quantity=1)

Apply only the directly observable accounting effects:

- subtract the item's current market price from player money
- add the purchased quantity to player inventory

Do NOT change:
- seeds
- farm
- opponent
- market prices
- market inventory
- day
- hour

IMPORTANT:
Do not assume that buying an item changes market inventory unless the
existing game observation/action semantics explicitly establish that.

The simulator should reject invalid purchases where:
- target is missing
- target has no market price
- quantity <= 0
- total cost exceeds current money

Use a clear exception type, preferably ValueError.

==================================================
3. SELL SIMULATION
==================================================

For:

Action(action_type="SELL", target=item, quantity=1)

Apply:

- add item_quantity * current market price to player money
- subtract quantity from player inventory

Do NOT change:
- seeds
- farm
- opponent
- market prices
- market inventory
- day
- hour

Reject invalid sales where:
- target is missing
- target has no market price
- quantity <= 0
- player does not own enough of the item

Use ValueError.

==================================================
4. PLANT SIMULATION
==================================================

For:

Action(action_type="PLANT", target=crop, quantity=1)

For this ticket, apply only the directly observable inventory effect:

- subtract the required seed quantity from player.seeds

Do NOT:
- create a crop growth system
- modify tiles
- place a crop on a specific coordinate
- advance time
- calculate harvests
- calculate yields
- create crop instances
- spend action tokens
- infer planting location

Reject invalid planting where:
- target is missing
- quantity <= 0
- player does not own enough of the seed

Use ValueError.

IMPORTANT:
If the existing code/model structure does not make the seed update safely
representable, do NOT invent a new crop system. Instead, report the
compatibility issue.

==================================================
5. UNSUPPORTED ACTIONS
==================================================

If the Simulator receives an action type other than:

- BUY
- SELL
- PLANT

raise ValueError.

Do not silently ignore unknown actions.

==================================================
6. IMMUTABILITY / COPY SAFETY
==================================================

The original GameState must remain unchanged.

The returned GameState must not share mutable mappings/sequences with
the original state in a way that allows a mutation of the simulated state
to mutate the original state.

Pay particular attention to:

- player.inventory.items
- player.seeds
- farm.tiles
- farm.hands
- farm.unlocked_quadrants
- market.prices
- market.inventory
- opponent.farm

Preserve the existing immutable dataclass architecture.

Use defensive copies where necessary.

Do not redesign the models just to make simulation easier.

==================================================
7. TESTS
==================================================

Create:

tests/test_planner_simulator.py

Test at minimum:

BUY:
1. Buying decreases player money by the current price.
2. Buying increases player inventory.
3. Buying does not mutate the original GameState.
4. Buying an unaffordable item raises ValueError.
5. Buying an unknown item raises ValueError.
6. Buying with invalid quantity raises ValueError.

SELL:
7. Selling increases player money by quantity * price.
8. Selling decreases player inventory.
9. Selling does not mutate the original GameState.
10. Selling more than owned raises ValueError.
11. Selling an unknown item raises ValueError.
12. Selling with invalid quantity raises ValueError.

PLANT:
13. Planting decreases the appropriate seed count.
14. Planting does not mutate the original GameState.
15. Planting without enough seeds raises ValueError.
16. Planting an unknown seed type raises ValueError.
17. Planting with invalid quantity raises ValueError.

GENERAL:
18. Unsupported action types raise ValueError.
19. The simulated state preserves day/hour.
20. The simulated state preserves market prices.
21. The simulated state preserves market inventory.
22. The simulated state preserves opponent state.
23. The simulated state preserves farm state.
24. Mutating simulated mappings does not mutate the original state.
25. Existing full test suite still passes.

Use the existing test helpers/fixtures wherever possible.

==================================================
8. IMPORTANT ARCHITECTURAL BOUNDARY
==================================================

The Simulator must NOT:

- choose actions
- rank actions
- score actions
- calculate ROI
- calculate expected value
- predict future prices
- simulate multiple turns
- advance time
- model crop growth
- model animal production
- model weather
- model opponent behavior
- create plans

This ticket is ONLY:

"Given the current state and ONE action, produce the immediate hypothetical
state transition that we can safely establish from our current models."

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