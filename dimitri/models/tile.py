"""Represents the observed contents of a single farm tile.

The Kaggriculture environment reports each farm tile as one of:

- ``None`` — an empty, unlocked tile.
- ``"LOCKED"`` — a tile in a quadrant the player has not yet bought.
- a dict whose ``kind`` is ``"PLANT"``, ``"WEED"``, ``"COOP"``, or
  ``"PASTURE"``. A coop or pasture dict additionally carries an
  ``animal`` key (and that animal's state) once an animal has been
  placed on it.

``None`` and ``"LOCKED"`` are already explicit, so they are kept as-is.
The dict structures are modeled here as frozen dataclasses whose
fields mirror the keys the environment actually writes (see
``_new_plant``, ``_new_animal``, and the ``DIG`` / ``BUILD_*`` / decay
handlers in ``kaggle_environments/envs/kaggriculture/kaggriculture.py``).
No field is invented, renamed in meaning, or derived.

Like the other models in this package, these classes store facts only.
They never compute crop age, readiness to harvest, watering urgency,
production schedules, or any other derived metric, and they never
make decisions. Those responsibilities belong to the Analyst, Planner,
and Executive modules downstream.
"""

from dataclasses import dataclass
from typing import Literal, TypeAlias

StructureKind: TypeAlias = Literal["COOP", "PASTURE"]
"""The two animal structures a player can build on a tile."""


@dataclass(frozen=True)
class PlantTile:
    """An immutable snapshot of a tile holding a growing plant.

    Mirrors a ``kind="PLANT"`` tile dict.

    Attributes:
        crop: The crop planted on the tile (e.g. ``"WHEAT"``).
        planted_day: The in-game day the crop was planted.
        watered_today: Whether the plant has been watered today.
        consecutive_unwatered: The number of consecutive end-of-day
            refreshes the plant has gone unwatered, as reported by the
            environment (planting day counts as unwatered).
        yield_units: Units of produce currently available to harvest.
        max_lifespan_step: The step after which the plant begins to
            decay, or ``-1`` when the environment has not yet set one.
        fertilized_until_day: The last day (inclusive) on which the
            fertilizer bonus applies, or ``-1`` if never fertilized.
    """

    crop: str
    planted_day: int
    watered_today: bool
    consecutive_unwatered: int
    yield_units: int
    max_lifespan_step: int
    fertilized_until_day: int


@dataclass(frozen=True)
class AnimalTile:
    """An immutable snapshot of a coop or pasture with an animal on it.

    Mirrors a ``kind="COOP"`` / ``kind="PASTURE"`` tile dict that
    carries an ``animal`` key.

    Attributes:
        structure: The structure the animal lives on (the tile's
            ``kind``): ``"COOP"`` or ``"PASTURE"``.
        animal: The animal on the tile (e.g. ``"GOOSE"``, ``"COW"``).
        placed_day: The in-game day the animal was placed.
        yield_units: Units of animal product currently available to
            harvest.
        consecutive_unfed: The number of consecutive end-of-day
            refreshes the animal has gone unfed.
        fed_today: Whether the animal has been fed today.
        cared_today: Whether the animal has been cared for today.
        fertilizer_available: Whether a unit of fertilizer is
            currently available to collect from the animal.
        pending_care_bonus: The banked care bonus awaiting the
            animal's next scheduled production.
    """

    structure: StructureKind
    animal: str
    placed_day: int
    yield_units: int
    consecutive_unfed: int
    fed_today: bool
    cared_today: bool
    fertilizer_available: bool
    pending_care_bonus: int


@dataclass(frozen=True)
class StructureTile:
    """An immutable snapshot of an empty coop or pasture.

    Mirrors a ``kind="COOP"`` / ``kind="PASTURE"`` tile dict with no
    ``animal`` key — either freshly built, or left behind after an
    animal escaped.

    Attributes:
        structure: The structure on the tile: ``"COOP"`` or
            ``"PASTURE"``.
    """

    structure: StructureKind


@dataclass(frozen=True)
class WeedTile:
    """An immutable snapshot of a tile overgrown by a weed.

    Mirrors a ``kind="WEED"`` tile dict, which carries no other data.
    """


TileContents: TypeAlias = PlantTile | AnimalTile | StructureTile | WeedTile
"""Anything that can occupy an unlocked farm tile."""
