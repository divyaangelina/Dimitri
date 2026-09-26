Implement Ticket #007: Observer for the Dimitri Kaggriculture agent.

## Mission

The Observer is the orchestration layer between raw Kaggle observations and the rest of Dimitri's pipeline.

Its sole responsibility is:

    Raw Kaggle observation
            ↓
          Parser
            ↓
        GameState
            ↓
        Validator
            ↓
      trusted GameState

The Observer must parse the raw observation into a GameState, validate that GameState, and return it.

## Current Architecture

Dimitri currently has:

dimitri/
├── models/
│   ├── game_state.py
│   ├── player.py
│   ├── inventory.py
│   ├── market.py
│   ├── crop.py
│   └── animal.py
│
├── observer/
│   ├── __init__.py
│   ├── observer.py
│   ├── parser.py
│   └── validator.py
│
├── analyst/
├── planner/
├── executive/
├── operator/
└── utils/

The current model hierarchy is:

GameState
├── day
├── player
│   ├── player_id
│   ├── money
│   └── inventory
│       └── items
├── market
└── raw_observation

Important:
Inventory belongs inside Player. GameState does NOT have a standalone inventory field.

## Existing APIs

Parser:

    parse(observation) -> GameState

Validator:

    validate(game_state) -> None

The Validator raises ValidationError if the GameState is structurally invalid.

Use these existing APIs rather than duplicating their logic.

## Required Implementation

Create/update:

    dimitri/observer/observer.py

Implement an Observer class with this public API:

    class Observer:
        def observe(self, observation: dict) -> GameState

The observe() method must:

1. Receive the raw Kaggle observation.
2. Pass it to parser.parse().
3. Receive the resulting GameState.
4. Pass that GameState to validator.validate().
5. Return the same GameState after successful validation.

Conceptually:

    class Observer:
        def observe(self, observation):
            game_state = parse(observation)
            validate(game_state)
            return game_state

## Important Design Constraints

The Observer must NOT:

- perform parsing itself
- duplicate Parser logic
- duplicate Validator logic
- calculate derived values
- perform economic analysis
- evaluate strategy
- make decisions
- generate plans
- inspect opponent behavior
- mutate the raw observation
- mutate the GameState
- maintain history
- cache state
- add speculative abstractions
- add unnecessary helper classes
- add future architecture that is not currently required

The Observer is an orchestration layer, not an intelligence layer.

## Error Handling

Do not swallow or replace errors from Parser or Validator.

If Parser raises ParseError, let it propagate.

If Validator raises ValidationError, let it propagate.

Do not silently recover, guess, or substitute values.

## Type Hints

Use Python 3.11+ type hints.

The public method should be:

    def observe(self, observation: dict) -> GameState:

Import GameState from:

    dimitri.models.game_state

Import parse from:

    dimitri.observer.parser

Import validate from:

    dimitri.observer.validator

## Documentation

Add a concise module docstring explaining the Observer's role.

Add a class docstring explaining that Observer orchestrates parsing and validation.

Add a method docstring for observe().

Documentation should emphasize that the Observer does not perform analysis or decision-making.

## Testing Expectations

Do not create a large testing framework or unrelated files.

The implementation should be compatible with the existing test suite and the upcoming integration test in Ticket #008.

The Observer should be usable like:

    observer = Observer()
    game_state = observer.observe(observation)

After observe() returns successfully, the returned GameState should already have passed Validator validation.

## Deliverable

Implement only Ticket #007.

Do not modify unrelated architecture or files unless absolutely necessary for imports to work.

After implementation, report:

1. What files were changed.
2. What was implemented.
3. Any assumptions made.
4. Any tests run and their results.