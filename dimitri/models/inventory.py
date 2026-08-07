"""Represents the contents of Dimitri's private storage.

Inventory models what Dimitri currently holds off the field: shed
contents, held seeds, and harvested produce awaiting sale. It is
composed into Player alongside money and player identity, keeping all
"what Dimitri owns" information grouped together.

Inventory deliberately excludes anything that is not carried resources.
It does not represent crops growing in the field, animals living on
the farm, buildings, or land ownership — those belong to other models
as Dimitri's architecture evolves.

Like the other models in this package, Inventory stores facts only. It
never performs reasoning, evaluation, or decision-making — no valuing
of held items, no sell/buy decisions, no shortage prediction, and no
tracking of future production. Those responsibilities belong to the
Analyst, Planner, and Executive modules downstream. Inventory exists
purely to be read.

Because it is a frozen dataclass, an Inventory instance cannot be
mutated after construction. Each new observation produces a new
Inventory rather than modifying an existing one.
"""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Inventory:
    """An immutable snapshot of Dimitri's held resources.

    Inventory is a pure data container. Rather than modeling each
    resource type as its own field (e.g. ``wheat: int``,
    ``tomatoes: int``), it stores all held quantities in a single
    ``items`` mapping keyed by resource name. This keeps the model
    resilient to new resources being introduced by the game — a new
    resource simply becomes a new key, with no changes required to
    this class.

    Inventory is responsible only for holding facts about what Dimitri
    currently possesses. It is explicitly not responsible for valuing
    those items, deciding what to sell or buy, predicting shortages, or
    making any other decisions — those responsibilities belong to the
    Analyst, Planner, and Executive modules, and remain fully
    independent of this model.

    Attributes:
        items: A mapping of resource name (e.g. "WHEAT", "EGG",
            "FERTILIZER") to the quantity of that resource currently
            held. Resources not present in the mapping should be
            treated as a quantity of zero by callers, typically via
            ``items.get("EGG", 0)``.
    """

    items: Mapping[str, int]
