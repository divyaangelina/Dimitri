"""Represents the shared town state reported by the Kaggle environment.

Town models the observation's ``town`` dict, which is shared by both
players. The environment reports a single field, ``unlocked_shops``,
listing the town shops that are currently active. The environment adds
one shop to this list at regular day intervals and never removes one.

Like the other models in this package, Town stores facts only. It
never looks up which products a shop demands, estimates demand, or
predicts future unlocks. Those responsibilities belong to the Analyst,
Planner, and Executive modules downstream. Town exists purely to be
read.

Because it is a frozen dataclass holding a tuple, a Town instance
cannot be mutated after construction.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Town:
    """An immutable snapshot of the shared town state.

    Attributes:
        unlocked_shops: The names of the currently unlocked town shops
            (e.g. ``"BAKERY"``), in the order the environment unlocked
            them.
    """

    unlocked_shops: tuple[str, ...]
