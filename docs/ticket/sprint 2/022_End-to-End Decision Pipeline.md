Ticket #022 — End-to-End Decision Pipeline

Goal:
Connect the existing Observer → Analyst → Planner → Executive → Operator layers into one minimal end-to-end pipeline.

This ticket is about integration, NOT strategy.

The desired flow is:

Kaggriculture observation
        ↓
     Observer
        ↓
    GameState
        ↓
     Analyst
        ↓
    Analysis
        ↓
     Planner
        ↓
candidate decisions
        ↓
    Executive
        ↓
selected decision
        ↓
    Operator
        ↓
Kaggriculture action dictionary

Task:

1. Inspect the existing implementations from Tickets #001–#021.

2. Create the smallest reasonable orchestration layer needed to connect these components.

3. The orchestration layer should:
   - accept a Kaggriculture observation
   - produce/obtain a GameState through the Observer
   - analyze the GameState
   - ask the Planner for candidate options
   - pass those candidates to the Executive
   - pass the Executive's selected decision to the Operator
   - return the final Kaggriculture-compatible action dictionary

4. Do not duplicate responsibilities already belonging to Observer, Analyst, Planner, Executive, or Operator.

5. The orchestration layer must NOT contain:
   - crop strategy
   - animal strategy
   - economic calculations
   - market predictions
   - opponent strategy
   - action ranking
   - low-level Kaggriculture action construction

6. Keep the current deterministic Executive behavior for now. We are validating the architecture, not building intelligence yet.

7. Add an end-to-end test using the existing sample observation in:
   tests/sample_observation.json

The test should verify that:
   observation
   → GameState
   → Analysis
   → candidates
   → selected decision
   → Kaggriculture action

works without manually bypassing any architectural layer.

8. Verify that the resulting action has the expected Kaggriculture structure:

{
    "farmer": [...],
    "hands": [...],
    "market": [...]
}

9. Add tests for at least:
   - successful end-to-end execution
   - a minimal/empty candidate situation
   - malformed input handling where appropriate

10. Do NOT implement sophisticated decision-making.

11. Do NOT refactor unrelated code.

12. Run:

python -m pytest -v

All existing tests plus the new integration tests must pass.

Important:
Before coding, inspect the existing interfaces carefully. Reuse the current models and action representations. Do not create duplicate abstractions just to make the integration test pass.