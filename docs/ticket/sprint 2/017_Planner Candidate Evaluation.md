Ticket #017 — Planner Candidate Evaluation

We are continuing Dimitri's architecture.

Goal:
Connect CandidateGenerator, Simulator, and Evaluator so the Planner can
evaluate every currently available candidate action.

Architecture:

FACTS → INFERENCES → CANDIDATE FUTURES → EVALUATION → DECISION

For this ticket, the Planner should produce an evaluation for every
candidate action.

It must NOT select a winner yet.

The Executive will eventually make the final action-selection/commitment
decision.

Read the existing implementation and tests before changing anything.
Preserve the current architecture. Do not perform unrelated refactors.

==================================================
1. CREATE PLANNER RESULT MODEL
==================================================

Create:

dimitri/planner/planning.py

Define an immutable dataclass:

@dataclass(frozen=True)
class CandidateEvaluation:
    action: Action
    resulting_state: GameState
    evaluation: Evaluation

This represents:

    "If Dimitri takes this action, the resulting state has this evaluation."

Also define:

@dataclass(frozen=True)
class PlanningResult:
    candidates: tuple[CandidateEvaluation, ...]

PlanningResult contains every evaluated candidate.

It must NOT contain:
- selected_action
- best_action
- winner
- recommendation
- ranking

The Planner does not choose yet.

==================================================
2. CREATE / UPDATE PLANNER
==================================================

Update:

dimitri/planner/planner.py

Define:

class Planner:
    def __init__(
        self,
        generator: CandidateGenerator | None = None,
        simulator: Simulator | None = None,
        evaluator: Evaluator | None = None,
    ):
        ...

    def plan(self, game_state: GameState) -> PlanningResult:
        ...

The default constructor should create the standard:
- CandidateGenerator
- Simulator
- Evaluator

Pipeline:

1. generator.generate(game_state)
2. For each candidate:
       simulator.simulate(game_state, action)
3. evaluator.evaluate(resulting_state)
4. create CandidateEvaluation
5. return all CandidateEvaluation objects inside PlanningResult

==================================================
3. PRESERVE CANDIDATE ORDER
==================================================

The order returned by CandidateGenerator must be preserved.

Do NOT:
- sort candidates
- rank candidates
- select a candidate
- discard lower-valued candidates
- break ties
- assign "best" labels

If there are 10 candidates, PlanningResult must contain 10
CandidateEvaluation objects.

==================================================
4. IMPORTANT STATE ISOLATION
==================================================

Every candidate must be simulated independently from the ORIGINAL
GameState.

Do NOT simulate candidate B starting from candidate A's resulting state.

Correct:

original → action A → state A
original → action B → state B
original → action C → state C

Incorrect:

original → action A → state A
state A → action B → state B
state B → action C → state C

The Planner is evaluating alternative futures, not a sequence of actions.

==================================================
5. EMPTY CANDIDATE SET
==================================================

If CandidateGenerator returns no candidates:

return:

PlanningResult(candidates=())

Do not invent an action.

Do not raise an exception merely because there are no candidates.

==================================================
6. NO DECISION MAKING
==================================================

Planner must NOT:

- select the best candidate
- rank candidates
- choose an action
- recommend an action
- break ties
- execute an action
- mutate GameState
- modify the real environment

The Planner's job for this ticket is:

"Generate and evaluate the available alternatives."

==================================================
7. TESTS
==================================================

Create:

tests/test_planner.py

Test at minimum:

1. Planner returns a PlanningResult.
2. Every generated candidate receives exactly one evaluation.
3. Candidate count equals PlanningResult.candidates count.
4. Candidate ordering is preserved.
5. Action in CandidateEvaluation matches the generated action.
6. Resulting state corresponds to that action.
7. Evaluation corresponds to the resulting state.
8. Candidate simulations are independent of one another.
9. Original GameState remains unchanged.
10. Empty candidate set produces PlanningResult(candidates=()).
11. PlanningResult is immutable.
12. CandidateEvaluation is immutable.
13. Identical input GameStates produce identical PlanningResults.
14. Planner does not contain or expose a selected/best action.
15. Existing full test suite still passes.

Use existing fixtures/helpers wherever possible.

==================================================
8. ARCHITECTURAL BOUNDARY
==================================================

Do not create:

- DecisionEngine
- RankingEngine
- StrategyEngine
- RecommendationEngine
- OptimizationEngine

Do not modify the responsibilities of:
- Analyst
- CandidateGenerator
- Simulator
- Evaluator
- Executive

The Planner orchestrates the existing components.

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