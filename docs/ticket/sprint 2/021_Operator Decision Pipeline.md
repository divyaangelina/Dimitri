Ticket #021 — Define the Planner → Executive → Operator Decision Pipeline

Goal:
Establish the clean handoff between planning, decision-making, and execution.

Dimitri's architecture is:

Observer
→ reads/parses Kaggriculture observations

Analyst
→ derives facts and metrics from GameState

Planner
→ generates and evaluates possible actions/plans

Executive
→ selects what Dimitri will actually do

Operator
→ converts the selected decision into a Kaggriculture-compatible action

Important architectural rule:

Planner proposes.
Executive decides.
Operator executes.

Neither Planner nor Operator should take over the Executive's responsibility.

Task:

1. Inspect the current Planner, Executive, Operator, action models, and relevant tests.

2. Define a small, explicit representation for a planner-generated candidate action/plan.

3. Define the representation of an Executive decision.

4. Establish a clean interface:

   Planner
       ↓
   candidate actions/plans
       ↓
   Executive
       ↓
   selected decision
       ↓
   Operator
       ↓
   Kaggriculture action dictionary

5. The Executive should accept candidate options and select one.

For now, the Executive does NOT need sophisticated strategy.

A deterministic placeholder selection policy is acceptable for this ticket, such as selecting the first valid candidate.

The purpose of this ticket is to establish the architectural boundary, not to make Dimitri strategically intelligent.

6. The Operator should receive only the Executive's selected decision/action.

7. The Operator must not:
   - compare candidates
   - rank candidates
   - calculate expected value
   - choose between alternatives
   - generate plans

8. The Executive must not:
   - directly construct the final Kaggriculture API dictionary
   - execute actions
   - contain low-level API translation logic

9. The Planner must not:
   - commit to an action
   - execute an action
   - contain Executive logic

10. Keep models/data immutable where appropriate and preserve the existing architecture's separation between facts, inference, decisions, and execution.

11. Add focused tests covering:
   - Planner produces candidate options
   - Executive receives candidates
   - Executive selects one candidate
   - selected decision can be passed to Operator
   - Operator converts the selected decision into the Kaggriculture action structure
   - Planner does not execute actions
   - Executive does not execute actions
   - Operator does not make decisions

12. Do NOT add:
   - crop strategy
   - animal strategy
   - ROI calculations
   - market predictions
   - opponent strategy
   - sophisticated scoring
   - multi-day optimization
   - new economic heuristics

13. Do not refactor unrelated code.

14. Run:

python -m pytest -v

All existing tests plus the new tests must pass.

Before implementing, inspect the existing code and reuse existing action abstractions where appropriate. Do not create duplicate action representations simply to satisfy this ticket.