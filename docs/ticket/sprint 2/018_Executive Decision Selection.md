Ticket #018 — Executive Decision Selection

We are continuing Dimitri's architecture.

Goal:
Create the Executive layer that selects ONE action from a PlanningResult.

Architecture:

FACTS → INFERENCES → CANDIDATE FUTURES → EVALUATION → DECISION

The Analyst understands the current state.
The Planner generates and evaluates alternatives.
The Executive makes the decision.
The Operator will eventually execute that decision.

For this ticket, Executive must ONLY select an action.

It must NOT execute the action or modify the GameState.

Read the existing implementation and tests before changing anything.
Preserve the current architecture. Do not perform unrelated refactors.

==================================================
1. CREATE EXECUTIVE
==================================================

Update:

dimitri/executive/executive.py

Define:

class Executive:
    def decide(self, planning_result: PlanningResult) -> Action:
        ...

The method must select exactly one Action from the provided
PlanningResult.

==================================================
2. SELECTION RULE
==================================================

Select the candidate with the greatest:

    evaluation.total_liquid_value

This is the ONLY selection criterion for this ticket.

Do not add:
- risk adjustments
- future growth estimates
- opportunity costs
- crop preferences
- animal preferences
- opponent modeling
- action costs
- strategic bonuses
- heuristics

Those belong in later decision-system work.

==================================================
3. TIE BREAKING
==================================================

If multiple candidates have the same total_liquid_value:

select the FIRST candidate in PlanningResult.candidates.

Because Planner preserves deterministic candidate ordering, this makes
Executive deterministic.

Do NOT sort candidates to break ties.

==================================================
4. EMPTY PLANNING RESULT
==================================================

If:

planning_result.candidates == ()

raise:

ValueError("Cannot decide without candidate actions")

Do not invent an action.

==================================================
5. RETURN VALUE
==================================================

Return the exact Action object from the selected CandidateEvaluation.

Do not create a copy or new Action unnecessarily.

==================================================
6. NO EXECUTION
==================================================

Executive must NOT:

- modify GameState
- call Operator
- call Kaggle environment APIs
- execute actions
- mutate inventory
- mutate money
- mutate farm state
- advance time
- generate new candidates
- simulate states
- evaluate states

Executive answers only:

"Which already-evaluated action should we commit to?"

==================================================
7. TESTS
==================================================

Create:

tests/test_executive.py

Test at minimum:

1. Executive selects the candidate with the highest total_liquid_value.
2. Executive returns the exact Action object from the winning candidate.
3. A lower-valued candidate is not selected when a higher-valued candidate
   exists.
4. Equal-valued candidates select the first candidate.
5. Empty PlanningResult raises ValueError.
6. Executive does not mutate PlanningResult.
7. Executive does not mutate any GameState contained in the result.
8. Repeated decisions with identical PlanningResults produce identical
   Actions.
9. Executive works with BUY actions.
10. Executive works with SELL actions.
11. Executive works with PLANT actions.
12. Existing full test suite still passes.

Use existing test helpers/fixtures wherever possible.

==================================================
8. ARCHITECTURAL BOUNDARY
==================================================

Do not create:

- DecisionEngine
- RankingEngine
- StrategyEngine
- OptimizationEngine
- RecommendationEngine

Do not move scoring logic into Executive.

The Evaluator owns state evaluation.
The Planner owns candidate generation/simulation/evaluation orchestration.
The Executive owns selection.

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