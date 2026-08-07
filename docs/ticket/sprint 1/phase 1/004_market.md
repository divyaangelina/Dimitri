📄 Engineering Ticket #004 — Market
Module
dimitri/models/market.py
Purpose
Market represents the shared marketplace visible to all players.
It stores the current market state exactly as observed from the Kaggle environment.
It is a component of GameState and acts as Dimitri's factual view of the economy.
Responsibilities
The Market model must:
Represent the current market prices.
Store immutable factual data.
Provide a clean interface to the current economy.
Be easy to inspect and debug.
Non-Responsibilities
Market must never:
Predict future prices.
Detect trends.
Recommend buying or selling.
Rank investments.
Estimate future profits.
Modify itself after construction.
These responsibilities belong to the Analyst.
Design Principles
The class should:
Be implemented as a frozen dataclass.
Store facts only.
Represent the economy, not economic reasoning.
Remain completely independent of planning and decision-making.
Initial Fields (Sprint 1)
I think we should mirror what we did with Inventory.
Instead of:
wheat_price: int
egg_price: int
milk_price: int
I propose:
prices: Mapping[str, int]
Why?
Exactly the same reasoning.
If Kaggle adds a new resource, the architecture shouldn't change.
Version 1
Market

prices: Mapping[str, int]
That's it.
No trend history.
No predictions.
No moving averages.
Those belong to the Analyst.
Future Expansion
Future versions may include:
Historical Prices
Supply
Demand
Market Events
Volatility
None of these belong in Sprint 1.
Remember:
Build the smallest useful model.
Public API
The model exposes data only.
No helper methods.
No calculations.
No business logic.
Documentation
The module docstring should explain:
what the market represents,
why it only stores facts,
why prices are represented as a mapping.
The class docstring should reinforce that all market interpretation belongs to the Analyst.
Success Criteria
The following should work naturally:
game_state.market.prices["WHEAT"]
or
game_state.market.prices.get("EGG", 0)
without interacting with raw Kaggle dictionaries.
Additional Notes
The Market model intentionally mirrors the design of Inventory.
Both represent dynamic collections of game resources.
Maintaining this symmetry keeps Dimitri's API predictable and easy to learn.