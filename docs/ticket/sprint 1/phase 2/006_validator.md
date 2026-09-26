📄 Engineering Ticket #006 — Validator
Module
dimitri/observer/validator.py
Purpose
The Validator verifies that a parsed GameState is structurally complete and safe for the remainder of Dimitri's pipeline.
It performs structural validation only.
It does not evaluate game logic or strategy.
Responsibilities
The Validator must:
Verify required models exist.
Verify required fields have the expected types.
Raise clear exceptions if validation fails.
Guarantee downstream modules receive a usable GameState.
Non-Responsibilities
The Validator must never:
Correct invalid data.
Guess missing values.
Perform calculations.
Enforce game strategy.
Make decisions.
Input
GameState
Output
Nothing.
If validation succeeds...
it returns normally.
If validation fails...
it raises:
ValidationError
Public API
Exactly one public function:
validate(game_state: GameState) -> None
Design Principles
The Validator should:
Be deterministic.
Have no side effects.
Fail loudly.
Prefer explicit error messages.
Documentation
Include:
module docstring
ValidationError
function docstring
Success Criteria
Valid GameState:
validate(game_state)
returns successfully.
Invalid:
ValidationError(...)
is raised.