TICKET #010 — ANALYST FOUNDATION

Context:
Dimitri's observation/state foundation is complete. The current architecture is:

Observer → GameState → Analyst → Planner → Executive → Operator

Sprint 1 and Ticket #009 are complete, and all 9 integration tests pass.

The Analyst is responsible for turning factual GameState data into derived facts and later inferences. It must NOT make decisions, select actions, rank investments, or create plans.

Goal:
Create the initial Analyst foundation and a small set of deterministic derived facts.

Requirements:

1. Create:
   dimitri/analyst/analyst.py

2. Create an immutable analysis result model. Put it in:
   dimitri/analyst/analysis.py

   It should contain only deterministic facts derived directly from GameState.

3. For this first ticket, the analysis result should include:
   - current_day
   - current_hour
   - days_remaining
   - current_money
   - number of unlocked farm tiles
   - number of locked farm tiles
   - number of occupied farm tiles
   - number of empty unlocked farm tiles

4. The Analyst must receive a GameState and return the analysis result.

   API:

       class Analyst:
           def analyze(self, game_state: GameState) -> Analysis:
               ...

5. Add a single constant for the total season length rather than hardcoding the number inside calculations. Put it in the appropriate existing constants module.

6. Tile classification:
   - None = empty unlocked tile
   - "LOCKED" = locked tile
   - any mapping/dict = occupied tile

   Use the Farm data already implemented. Do not invent new tile models.

7. The Analyst must NOT:
   - choose crops
   - choose animals
   - recommend actions
   - calculate ROI
   - rank investments
   - predict prices
   - analyze opponent strategy
   - generate plans
   - simulate future states
   - mutate GameState
   - modify the raw observation

8. Keep the implementation simple. Do not create additional abstractions unless they are required by the above contract.

9. Add unit tests covering:
   - correct current day/hour
   - correct days remaining
   - correct money
   - correct unlocked/locked/occupied/empty tile counts
   - a farm containing a mixture of all tile types
   - GameState remains unchanged after analysis

10. Run the complete test suite:

       python -m pytest -v

Success criteria:
- All existing tests continue to pass.
- New Analyst tests pass.
- The Analyst contains no decision-making or strategy.
- The implementation follows the existing immutable-model architecture.
- Do not modify Observer, Parser, Executive, Planner, or Operator unless absolutely necessary for imports/tests.
- Do not refactor unrelated code.

Before implementing, inspect the existing repository and current models/tests so the implementation matches the project's established conventions.