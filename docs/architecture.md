# Dimitri Architecture

## Current pipeline

```
observation
  → Observer   → GameState       (dimitri/observer)
  → Analyst    → Analysis        (dimitri/analyst)
  → Planner    → PlanningResult  (dimitri/planner)
  → Executive  → Decision        (dimitri/executive)
  → Operator   → action dict     (dimitri/operator)
```

Today the Planner works one action at a time: each generated Action
becomes a single-action candidate Turn, plus the idle `Turn()`. Each is
simulated one turn ahead and scored by cash, and the Executive commits to
the best candidate.

## Plan generation

```
Opportunity
    ↓
PlanGenerator      generate(game_state, opportunity) -> tuple[Plan, ...]
    ↓
Plan
    ↓
PlanEvaluator      evaluate_plan(game_state, plan) -> PlanEvaluation
```

A `PlanGenerator` (`dimitri/planner/plan_generator.py`) builds concrete
Plans for one kind of Opportunity from the current GameState. It returns
no plans for any other kind of opportunity, or when no valid plan can be
built. Every plan it returns can be played by `Simulator.simulate_plan`
from that state.

**Plan generation constructs hypotheses. It does not determine whether a
hypothesis is desirable.** A generator never evaluates, scores, ranks or
compares plans.

**Economic hypotheses are separate from mechanical scheduling.**

| Component | Decides |
|---|---|
| `PlanGenerator` | *What* economic hypothesis to test: one incremental investment |
| `FarmScheduler` | *How* to realize it while maintaining the farm that already exists |
| `Simulator` | *What happens* |
| `ContinuationEvaluator` | *Which* future ends with the most bank cash |

A Plan still has exactly one Opportunity: the **incremental** hypothesis it
tests. Care for plants already on the farm is background work done by the
same plan, not an extra opportunity. `Plan`, `Opportunity` and
`ContinuationEvaluator` are unchanged.

**A crop generator must be able to continue its crop from an already
observed intermediate lifecycle state, not only initiate a new crop.**
Dimitri observes and replans every turn, so a plan built partway through
an investment must finish that investment rather than start another.

### Hypotheses

The concrete generators are `WheatPlanGenerator` (`WHEAT_PRODUCTION`) and
`TomatoPlanGenerator` (`TOMATO_PRODUCTION`). Each proposes **at most one
hypothesis per state**, by this precedence:

1. **Continue the existing investment.**
   - Wheat: the oldest living wheat that can be kept alive.
   - Tomato: every living tomato that still has value, plus the held tomato
     seeds, planted as the unfinished part of a wave.
2. **Sell held output** of the crop that the farmer carries or the shed
   holds.
3. **Start the crop.**
   - Wheat: one plant, using a held seed before buying one.
   - Tomato: plant the held seeds as a wave, or else a **capacity wave**.

**The capacity wave** buys `k` seeds up front and plants `k` tomatoes,
where `k` is the largest wave that money, empty tiles and daily care
capacity allow. Daily care capacity is the planting tiles whose daily
watering tour, together with every living plant that still has value, fits
in one day.

If the wave can't be scheduled without losing a plant, `k` is reduced one
at a time. Sizes above `max_tomato_plantings` are skipped, because the
scheduler would reject them anyway. A planting takes a PLANT and a WATER
turn on the same day plus a move between distinct tiles, so a day of
`T` turns fits at most `(T + 1) // 3` plantings. Only days on which a
tomato planted on the spawn tile (the easiest case) could still produce
something sellable count. The bound skips only infeasible sizes; it never
chooses a wave size.

Feasibility isn't monotonic in `k`: a farm can fit six plantings but not
five. So the search stays a decrement, not a bisection. That is mechanical feasibility, not economic branching: only one
tomato hypothesis is ever returned. **The capacity wave is not claimed to
be economically optimal.** It is the one wave Dimitri currently knows how to
propose.

Held seeds can't be traced to the wave they were bought for, so every held
tomato seed counts as part of the wave. Buying a wave's seeds up front is
what makes a replan after observation continue the same wave.

### The FarmScheduler

`FarmScheduler.schedule(state, hypothesis)`
(`dimitri/planner/farm_scheduler.py`) realizes a hypothesis turn by turn
on the Simulator. Its jobs are **derived purely from the current
GameState** every turn and never stored. Each living WHEAT or TOMATO plant
yields its crop's jobs, and every job has a priority:

1. **SURVIVAL**: water a plant that dies tonight without it.
2. **VALUE**: a harvest whose yield is lost if delayed. That means a
   decaying plant, a tomato on its harvest day or at its maximum yield, or
   any harvest on the season's last day.
3. **CONSTRUCTION**: plant the hypothesis's next seed. This only happens if
   planting, the same-day water and every other job due today still fit in
   the day, and only if the new plant can still produce something sellable.
4. **ROUTINE**: daily watering, and harvests that can wait.

**Deadlines come first.** Within a priority, the nearest job comes first,
then the lower row, then the lower column. The farmer takes straight-line
steps; no pathfinding or route optimization is used.

Crop rules:

- **Wheat**: water daily, except right before a harvest the water wouldn't
  enlarge. Harvest on the first turn it can be harvested.
- **Tomato**: water daily until its harvest day and let yield accumulate.
  Harvest once on the day after its **last useful production**: the latest
  one refreshed in season whose harvest can still be walked back, dropped
  and sold by the season's last action. It is harvested earlier at its
  maximum yield. A spent tomato gets no care. No fertilizer is used.

Timing:

- A new plant is watered the turn after planting, so planting happens at
  hour 22 at the latest.
- The night returns the farmer to the spawn tile and drops its load.
- On the season's last turns, the final sale takes precedence over other
  work.

Market orders share the farmer's turns:

- Seeds are bought in the first turn, alongside the farmer's first action.
- A seed can't be planted in the turn it is bought, because market orders
  apply after unit actions.
- The plan ends by dropping carried crops at the spawn tile and selling
  **every WHEAT and TOMATO in the shed in the same turn**.

**Plan boundary.** A plan ends once its hypothesis has been realized, meaning
its plants have had their last harvest and the output is sold. Background
plants keep whatever condition the simulation left them in, alive and
cared for today, for the next plan to continue.

**Background plants are preserved.** If the hypothesis can't be realized
without losing a plant that still has value and could be maintained, the
scheduler rejects it and the generator returns no plan. A plant the farmer
can't reach before it dies tonight is exempt. Natural decay of a spent
plant is not a loss. There is no deliberate strategic abandonment yet:
holding cash is the only way to let plants go.

Current limitations:

- Wheat is one plant per hypothesis.
- Tomato is one capacity wave per state.
- No new wheat is planted inside a tomato plan, or the other way round.
- Watering is daily; there is no every-other-day optimization.

Timing is read from the Simulator as the turns are built. The live
pipeline does not call plan generators yet.

## Simulator

| Method | Simulates |
|---|---|
| `simulate_turn(state, turn)` | One action phase: the turn's unit actions, then market orders. Time does not advance. |
| `advance_turn(state)` | One time phase: town consumption and price refresh, plant decay, the end-of-day sweep on a day's last turn, then the clock moves on one turn. |
| `play_turn(state, turn)` | One complete game turn: `simulate_turn` then `advance_turn`. |
| `simulate_plan(state, plan)` | Every turn in `plan.turns`, in order, using `play_turn`. |

The Planner's current candidates use `simulate_turn`, so each is judged on
its immediate effect. Nothing in the decision pipeline calls
`simulate_plan` yet.

`simulate_plan` plays only the turns listed in the plan, and time advances
once per turn. The horizon does not add idle turns. An empty plan returns
an unchanged copy of the state. If a turn can't be simulated from the
state it's played on, a `ValueError` names the turn's index; nothing is
skipped or replaced with PASS. The caller's state is never modified.

**Plan simulation produces a hypothetical future GameState. It does not
determine whether the Plan is desirable.** Judging that future is a
separate step.

The Simulator assumes the opponent does nothing, and it does not model
the two random end-of-day effects (weed spawns and town-shop unlocks).

**Simulation is copy-on-write.** Every rule builds new mappings, sequences
and dataclasses for what it changes, and never mutates the state it was
given. So the intermediate states of a simulation share unchanged
containers with their input instead of each being deep-copied. The state a
public method returns is **isolated**, once per call: a deep copy that
shares nothing mutable with the input or any other result.

The FarmScheduler chains many turns. It plays them with
`play_turn(state, turn, isolated=False)`, and the generator isolates only
the final state with `Simulator.isolate`, so building a plan costs one copy,
not one per turn. A state from an unisolated chain must not be mutated or
handed on. This is what makes continuation search fast enough: profiling
showed deep copies were about 90% of its time.

**Exact fast paths.** Each of these skips work whose result is already
known, so states are identical to doing the work:

- **Turns where the farm can't change.** `farm_after_turn` changes tiles
  only through the end-of-day sweep (on a day's last turn) and plant
  decay (`decays_at`: a plant whose `max_lifespan_step` has been reached,
  every second step). When `changes_after_turn` rules both out, the farm
  is returned as it is, with no tile visited. The Simulator then keeps the
  Player or Opponent whose farm didn't change.
- **Unchanged tile grids.** Under copy-on-write, a turn that changes no
  tile leaves the same grid object. The FarmScheduler checks for lost
  plants only when the grid object changed.

Sharing these unchanged objects internally is what copy-on-write allows.
Public results are still isolated once.

**`raw_observation` is observational data, not simulation state.** Nothing
in the Simulator reads or changes it. Intermediate states share the input's
`raw_observation`, and an isolated state gets its own copy, so changing a
result, including its `raw_observation`, never affects the original or any
other result.

## Evaluation

| Model | Evaluates | Produced by |
|---|---|---|
| `CandidateEvaluation` | One immediate Turn: the state right after it and that state's cash-only `Evaluation`. The Executive chooses among these. | `Planner.plan` |
| `PlanEvaluation` | The factual economic result of a multi-turn hypothetical Plan. | `PlanEvaluator.evaluate_plan(state, plan)` |

`PlanEvaluator` simulates the plan with `Simulator.simulate_plan` and reads
the starting and final states:

- `starting_cash` and `ending_cash` are bank money only. Unsold goods and
  held seeds are never counted as cash.
- `cash_delta` is `ending_cash - starting_cash`.
- `starting_day` and `ending_day` come from the states' clocks.
- `turns_elapsed` is the number of turns simulated, `len(plan.turns)`,
  never the horizon.

**PlanEvaluation describes what happened in simulation. It does not decide
whether the Plan is desirable.** It has no score, ranking or
recommendation, and nothing in the decision pipeline uses it yet.

## Plan comparison

| Layer | Question |
|---|---|
| `PlanEvaluation` | What happened when this Plan was simulated? |
| `PlanComparison` | What measurable differences exist between two PlanEvaluations? |
| Strategic decision (future work) | Which Plan should Dimitri pursue? |

`compare_plans(evaluation_a, evaluation_b)` in
`dimitri/planner/plan_comparison.py` returns a `PlanComparison`. Each field
is plan A's value minus plan B's:

- `ending_cash_difference`
- `cash_delta_difference`
- `turns_elapsed_difference`
- `ending_day_difference`

It only does arithmetic: it doesn't simulate, evaluate or modify anything.

Plans can only be compared from the same decision point. The two
evaluations must have the same `starting_cash` and the same
`starting_day`, otherwise `compare_plans` raises `ValueError`.

**PlanComparison does not determine which Plan is preferable.** A plan
that earns more but takes longer is reported as exactly that: a positive
cash difference and a positive time difference. It never combines money
and time into a rate such as cash per day or ROI, and never values unsold
goods. Decisions that trade off money, time, risk or opportunity cost are
left to a future strategic layer.

## Continuation evaluation

| Layer | Question |
|---|---|
| `PlanEvaluation` | What happens during this concrete Plan? |
| `ContinuationEvaluation` | What terminal cash is projected if we continue planning from the resulting state until the season ends? |

**Terminal bank cash is the strategic objective.** The competition scores
each player by bank money at the end of the season. The agent acts on
steps 0 to 718 (`LAST_ACTION_STEP`), and the final observation at step
719 carries the reward.

`ContinuationEvaluator.evaluate(state)` (`dimitri/planner/continuation.py`)
considers these branches:

- **HOLD_CASH, the baseline, which is always available.** No further
  actions, so the projection is the current bank cash. It needs no
  simulation.
- **Every concrete plan from the configured PlanGenerators.** Each plan is
  simulated with `simulate_plan`, and the evaluator is applied again to the
  resulting state. Repeated cycles and reinvestment happen naturally,
  without being written into any rule.

It returns the branch with the greatest projected terminal cash. The
result includes `plans`, the sequence of plans that reaches it; this is
empty when holding cash does as well. On ties the earlier branch wins,
with HOLD_CASH first.

- Every branch runs to the same season endpoint, so plans of different
  lengths are compared by terminal cash, never by their own `cash_delta`.
- Unsold goods are not wealth.
- There is no discounting, time penalty or rate.

The current continuation capabilities are **HOLD_CASH, WHEAT_PRODUCTION
(one wheat) and TOMATO_PRODUCTION (one capacity wave)**. The search is exact
**over the hypotheses the generators propose**. Restricting tomato to one
wave size per state limits that hypothesis space; it doesn't make the
chosen size globally optimal. The default generators are
`WheatPlanGenerator` and `TomatoPlanGenerator`, in that order. Branches such as wheat then tomato,
tomato then tomato, or tomato then holding cash arise from regenerating
plans from each resulting state; nothing hard-codes them.

Recursion always ends, for three reasons:

- every accepted plan has at least one turn and must advance the clock;
- plans running past step 718 are rejected;
- a state past step 718 ends at its current cash.

A generated plan that can't be simulated breaks the generator's contract,
and raises `ValueError`.

**Simulation results are reused, not repeated.** A generator that simulates
a plan while building it can return it through
`PlanGenerator.generate_with_states` as a `GeneratedPlan(plan,
resulting_state)`. The resulting state is exactly what
`Simulator.simulate_plan` would produce. The ContinuationEvaluator
continues from that state and simulates only plans that arrive without
one. The default implementation attaches no state, so a generator that
only implements `generate` still works. `WheatPlanGenerator` provides the
state.

Projections are **deterministic under the current Simulator assumptions**:
an idle opponent, and no random weeds or town-shop unlocks. They are
model estimates, not guaranteed outcomes. **The live decision pipeline
does not use ContinuationEvaluation yet.**

## Planning hierarchy: Opportunity → Plan → Action

Dimitri is moving toward hybrid planning. Three levels are kept apart:

| Level | Question | Model |
|---|---|---|
| **Opportunity** | What could we potentially pursue? | `Opportunity` (`dimitri/analyst/opportunity.py`) |
| **Plan** | What sequence of actions would pursue it? | `Plan` (`dimitri/planner/plan.py`) |
| **Action** | What do we execute right now? | `Action` and `Turn` (`dimitri/planner/action.py`, `turn.py`) |

For example:

```
Opportunity: TOMATO_PRODUCTION
Plan:        BUY_SEED TOMATO 1 → PLANT TOMATO → WATER → … → HARVEST → DROP → SELL TOMATO 1
Action:      this turn's Turn, e.g. Turn(market=(Action(BUY_SEED, "TOMATO", 1),))
```

### Opportunity

A kind of thing Dimitri could pursue (`OpportunityKind`):
`WHEAT_PRODUCTION`, `CARROT_PRODUCTION`, `TOMATO_PRODUCTION`,
`STRAWBERRY_PRODUCTION`, `MELON_PRODUCTION`, `ANIMAL_PRODUCTION`,
`MARKET_TRADE`, `LAND_EXPANSION`, `HOLD_CASH`.

An Opportunity is descriptive. It is not a decision. It carries no
recommendation, score, probability, evaluation or executable action.

### Plan

A concrete hypothesis for pursuing one Opportunity:

- `opportunity`: the Opportunity it pursues;
- `turns`: the intended `Turn` for each game turn from the plan's start
  (waiting is an explicit idle `Turn()`);
- `horizon`: how many game turns the plan spans, declared rather than
  calculated, and at least `len(turns)`;
- `label`: an optional human-readable name.

A Plan reuses the existing `Turn` and `Action` models. There is no second
action representation, and a Plan carries no score or evaluation.

**Plans are hypotheses, not commitments.** Dimitri should be able to
re-evaluate a plan after observing the actual game state again. Only the
current turn is ever executed; the rest of a plan may be revised or
dropped on the next observation. A plan need not be executable today,
because its later turns may depend on state that does not exist yet.

### Action

The existing `Action` and `Turn` remain the only executable
representation. The Operator writes a decided `Turn` in the Kaggriculture
API format.

## Status

`Opportunity` and `Plan` are data models only. Nothing produces or
consumes them yet. Opportunity detection, plan generation, multi-turn
simulation, plan evaluation and plan selection are future work, and the
current Planner → Executive → Operator flow is unchanged.
