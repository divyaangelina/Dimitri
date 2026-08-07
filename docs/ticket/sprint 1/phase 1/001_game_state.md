📄 Engineering Ticket #001 — GameState
Module
dimitri/models/game_state.py
Purpose
GameState is the central data model used throughout Dimitri.
It represents Dimitri's complete understanding of the game at a single moment in time and acts as the single source of truth shared by every module.
Every major component (Observer, Analyst, Planner, Executive, and Operator) will interact with GameState instead of raw Kaggle observations.
Responsibilities
The GameState class must:
Represent the current game state.
Store only factual information.
Be immutable after creation.
Be simple to inspect and debug.
Be independent of any decision-making logic.
Be the primary object passed between Dimitri's modules.
Non-Responsibilities
GameState must never:
Calculate ROI.
Detect bottlenecks.
Rank investments.
Predict market trends.
Build plans.
Choose actions.
Modify itself after creation.
These responsibilities belong to the Analyst, Planner, and Executive.
Design Principles
GameState should:
Be implemented as a frozen Python dataclass.
Store data, not behavior.
Favor composition over deeply nested dictionaries.
Be easy to serialize for debugging and testing.
Be readable enough that a human can inspect it and understand the game state.
Initial Fields (Version 1)
We intentionally want to keep Version 1 small.
GameState

day: int

player: Player

market: Market

inventory: Inventory

raw_observation: dict
These are enough for Sprint 1.
More fields will be added incrementally as Dimitri evolves.
Future Expansion
Future versions may include:
Opponent
Workers
Buildings
Land
Crops
Animals
History
Alerts
Events
These are intentionally excluded from Version 1 to keep Sprint 1 focused.
Dependencies
GameState depends on:
Player
Market
Inventory
These should be separate dataclasses.
Public API
The class should expose data only.
No business logic.
No helper methods (other than those automatically provided by the dataclass).
Success Criteria
A successful implementation should allow code like:
game_state.day

game_state.player.money

game_state.market

game_state.inventory
without requiring dictionary lookups.
Documentation
The module should contain a module-level docstring explaining its role.
The class should contain a class-level docstring explaining its responsibility.
Both should clearly state that GameState stores facts only and never performs analysis or decision-making.
Additional Notes
This is the foundational model for Dimitri.
Every future module will depend on it.
Correctness, clarity, and maintainability are significantly more important than cleverness or optimization.