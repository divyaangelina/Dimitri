📄 Engineering Ticket #005 — Parser (Final Version)
Module
dimitri/observer/parser.py
Purpose
The Parser translates raw Kaggle observations into Dimitri's internal data models.
It acts as the boundary between the external Kaggle API and Dimitri's architecture.
The Parser is responsible only for translating data into structured objects.
It performs no reasoning, validation, or decision-making.
Responsibilities
The Parser must:
Read the raw Kaggle observation dictionary.
Extract the information required by Dimitri's models.
Construct the appropriate model objects (Player, Inventory, Market, etc.).
Return a GameState.
Non-Responsibilities
The Parser must never:
Validate business rules.
Guess missing values.
Perform calculations.
Detect bottlenecks.
Predict anything.
Make decisions.
Input
observation: dict
Output
GameState
Algorithm
The parser should follow these steps:
Receive the raw observation dictionary.
Extract the current day.
Parse the player information.
Parse the inventory.
Parse the market.
Construct immutable model objects.
Return a fully populated GameState.
Error Handling
If required fields are missing or malformed:
Raise a clear exception.
Do not attempt to repair the input.
Do not silently substitute default values.
Design Principles
The Parser should:
Be deterministic.
Have no side effects.
Never modify the input dictionary.
Be easy to unit test.
Remain independent of the Analyst, Planner, Executive, and Operator.
Public API
Exactly one public function:
parse(observation: dict) -> GameState
Private helper functions are encouraged.
For example:
_parse_player()

_parse_inventory()

_parse_market()
Documentation
Include:
a module docstring,
function docstrings,
type hints throughout.
The documentation should clearly state that the Parser translates data and performs no reasoning.
Success Criteria
Given a valid Kaggle observation:
game_state = parse(observation)
should return a fully populated immutable GameState.
No dictionaries from the Kaggle API should escape into the rest of Dimitri's architecture except for the preserved raw_observation.