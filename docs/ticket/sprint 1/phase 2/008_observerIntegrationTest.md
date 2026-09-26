Implement Ticket #008: Observer Integration Test for the Dimitri Kaggriculture agent.

## Mission

Create an integration test that verifies the complete observation pipeline:

    tests/sample_observation.json
              ↓
          Observer
              ↓
           Parser
              ↓
          GameState
              ↓
          Validator
              ↓
       trusted GameState

This is the final ticket of Sprint 1.

The goal is to prove that the Parser, Validator, and Observer work together correctly using a real Kaggriculture observation captured during Discovery Ticket D-001.

## Current Architecture

The observation layer is:

    Raw Kaggle observation
            ↓
          Parser
            ↓
        GameState
            ↓
        Validator
            ↓
      trusted GameState

The Observer orchestrates the Parser and Validator.

Current Observer API:

    observer = Observer()
    game_state = observer.observe(observation)

Current model hierarchy:

    GameState
    ├── day
    ├── player
    │   ├── player_id
    │   ├── money
    │   └── inventory
    │       └── items
    ├── market
    └── raw_observation

IMPORTANT:
Inventory belongs inside Player.
GameState does NOT have a standalone inventory field.

## Sample Observation

Use the existing file:

    tests/sample_observation.json

This file was generated from an actual Kaggriculture environment observation during Discovery Ticket D-001.

Do not replace it with a newly invented fixture unless absolutely necessary.

## Test Location

Create:

    tests/test_observer_integration.py

Use the project's existing testing conventions if any already exist.

Prefer pytest if pytest is already being used by the project.

## Required Test

The integration test must:

1. Load tests/sample_observation.json.
2. Create an Observer.
3. Pass the loaded observation to Observer.observe().
4. Confirm that observe() returns a GameState.
5. Confirm that the resulting GameState contains the expected values from the sample observation.

At minimum, verify:

    game_state.day

    game_state.player.money

    game_state.player.inventory.items

    game_state.market.prices["WHEAT"]

For the current sample observation, the expected values are:

    day == 0

    player.money == 3000

    player.inventory.items is an empty mapping

    market.prices["WHEAT"] == 25

The test should also verify that the nested hierarchy is correct:

    game_state.player.inventory

exists and is an Inventory.

Do NOT test:

    game_state.inventory

because that field does not exist in the current architecture.

## Additional Integration Checks

Add focused tests where useful to verify the actual pipeline behavior.

At minimum, verify that:

- A valid sample observation successfully passes through Observer.
- The returned object is a GameState.
- Parser and Validator are actually being exercised through Observer rather than duplicated inside the test.
- The sample observation is not mutated by the observation pipeline.

If testing mutation, load the JSON into a Python object, make a deep copy before calling Observer.observe(), then compare the two afterward.

## Error Propagation

Add a small number of focused tests if appropriate to verify that Observer does not swallow upstream errors.

For example:

- An invalid observation that Parser cannot parse should cause ParseError to propagate.
- A GameState that Validator rejects should cause ValidationError to propagate.

Do not overbuild this.

The purpose is integration testing, not exhaustive unit testing of Parser or Validator. Their individual responsibilities are already tested separately.

## Test Design Constraints

Do NOT:

- modify production architecture
- modify Parser behavior
- modify Validator behavior
- modify Observer behavior
- add new models
- add new abstractions
- duplicate Parser logic in the tests
- duplicate Validator logic in the tests
- create speculative future tests
- introduce mocks unless genuinely necessary
- create a second sample observation
- change the existing sample observation simply to make the test easier

The integration test should test the real components together.

## Imports

Use the existing project modules, including:

    from dimitri.models.game_state import GameState
    from dimitri.models.inventory import Inventory
    from dimitri.observer.observer import Observer

Use pathlib or another clean standard-library approach to locate:

    tests/sample_observation.json

Do not hard-code an absolute filesystem path.

## Test Expectations

Run the complete relevant test suite after implementing the integration test.

Report:

1. Files created or modified.
2. Tests added.
3. Test command(s) run.
4. Number of tests passed/failed.
5. Any failures and their causes.

If an existing test fails because of an unrelated pre-existing issue, clearly distinguish that from failures caused by Ticket #008.

## Definition of Done

Ticket #008 is complete when:

- tests/test_observer_integration.py exists.
- It loads the real sample_observation.json.
- It exercises Observer.observe().
- It verifies the resulting GameState and nested Player → Inventory hierarchy.
- It verifies representative day, money, inventory, and market values.
- The sample observation is not mutated.
- Relevant error propagation is covered without overtesting.
- The test suite passes.

Do not make unrelated changes.