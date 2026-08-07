📄 Engineering Ticket #002 — Player
Module
dimitri/models/player.py
Purpose
Player represents Dimitri's current state within the game.
It is the canonical representation of everything Dimitri currently owns or controls.
Player stores factual information only and serves as a component of GameState.
Responsibilities
The Player model must:
Represent Dimitri's observable state.
Store immutable data.
Store ownership information.
Compose related models such as Inventory.
Be easy to inspect and debug.
Non-Responsibilities
Player must never:
Calculate ROI.
Detect bottlenecks.
Evaluate investments.
Predict future income.
Decide actions.
Modify itself after construction.
Design Principles
The class should:
Be implemented as a frozen dataclass.
Favor composition over primitive fields.
Represent ownership rather than behavior.
Remain independent of the Analyst and Planner.
Initial Fields (Sprint 1)
Player

player_id: int

money: int

inventory: Inventory
That's all.
Nothing else.
Future Expansion
Future versions may include:
Animals
Crops
Buildings
Workers
Land
Farmer Position
Statistics
These should not be implemented during Sprint 1.
Dependencies
Player depends on:
Inventory
Public API
The model exposes data only.
No helper methods.
No calculations.
No business logic.
Documentation
The module should contain a professional module docstring.
The class should contain a professional class docstring.
Both should emphasize that Player represents Dimitri's observable state and does not perform reasoning or decision-making.
Success Criteria
The following should be possible:
game_state.player.money

game_state.player.inventory
without requiring dictionary access.
Additional Notes
Player is intentionally small.
It will evolve alongside Dimitri as new capabilities are added.
The goal of Sprint 1 is to build a clean and maintainable foundation, not to model every aspect of the game immediately.