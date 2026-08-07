📄 Engineering Ticket #003 — Inventory
Module
dimitri/models/inventory.py
Purpose
Inventory represents the contents of Dimitri's private storage (shed, held items, seeds, harvested produce, and other carried resources).
It is a component of Player and stores only factual information about what Dimitri currently possesses in inventory.
It does not represent crops growing in the field, animals on the farm, buildings, or land ownership.
Responsibilities
The Inventory model must:
Represent Dimitri's stored resources.
Store immutable factual data.
Group related inventory information into a single model.
Be easy to inspect and debug.
Non-Responsibilities
Inventory must never:
Calculate inventory value.
Decide what to sell.
Decide what to buy.
Predict shortages.
Track future production.
Modify itself after construction.
Design Principles
The class should:
Be implemented as a frozen dataclass.
Store data only.
Keep related inventory information together.
Remain independent of game logic.
Initial Fields (Sprint 1)
Here's where I want to be careful.
We could model every resource separately...
wheat: int
tomatoes: int
eggs: int
milk: int
...
But I actually think that's a mistake.
Instead...
I propose:
items: Mapping[str, int]
Why?
Because Kaggle may add resources later.
If tomorrow they introduce pumpkins...
our architecture shouldn't need to change.
We'd simply have:
items["PUMPKIN"] = 5
No new field.
No new dataclass.
No migration.
So Version 1 becomes:
Inventory

items: Mapping[str, int]
That's it.
Future Expansion
Possible future additions:
Capacity
Reserved Items
Item Metadata
These are intentionally excluded from Sprint 1.
Public API
The model exposes data only.
No helper methods.
No calculations.
No business logic.
Documentation
Include professional module and class docstrings explaining:
what inventory represents,
what it deliberately excludes,
why it exists as a separate model.
Success Criteria
The following should be possible:
game_state.player.inventory.items["WHEAT"]
or
game_state.player.inventory.items.get("EGG", 0)
without using raw Kaggle dictionaries.