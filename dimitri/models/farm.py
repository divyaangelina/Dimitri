"""Represents the physical board state of a single player's farm.

Farm models the layout of one player's farm exactly as the Kaggle
environment reports it: the tile grid, unit positions, which land
quadrants are owned, and how many farm hands have been hired so far
today. This information is public — the rules document is explicit
that each farm dict is "visible to both players" — which is why Farm
is composed into both Player and Opponent. Only shed contents and
seeds (modeled by Inventory and Player.seeds) are private.

Like the other models in this package, Farm stores facts only. It
never interprets tile contents, evaluates land or expansion value,
plans hiring, or makes any decisions. Those responsibilities belong to
the Analyst, Planner, and Executive modules downstream. Farm exists
purely to be read.

Because it is a frozen dataclass, a Farm instance cannot be mutated
after construction. Each new observation produces a new Farm rather
than modifying an existing one.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

TileValue: TypeAlias = None | Literal["LOCKED"] | Mapping[str, Any]
"""The value of a single tile on a farm's board.

A tile is ``None`` when it is empty and unlocked, the literal string
``"LOCKED"`` when it sits in a quadrant the player has not yet bought,
or a structured mapping (a plant, weed, or animal structure) when
something occupies it. Dimitri does not yet model plant and animal
tile contents as their own types — that modeling is out of scope for
this ticket — so occupied tiles are represented here as opaque
mappings rather than invented dataclasses.
"""


@dataclass(frozen=True)
class Farm:
    """An immutable snapshot of one player's farm board.

    Farm is a pure data container. It represents the board exactly as
    observed — tile contents, positions, ownership, and today's hire
    count — not any interpretation of it. All evaluation of tile
    value, expansion strategy, or hiring decisions belongs to the
    Analyst, Planner, and Executive modules, and remains fully
    independent of this model.

    Attributes:
        tiles: The farm's board, indexed as ``tiles[y][x]``. Each
            entry is a TileValue: ``None`` (empty, unlocked),
            ``"LOCKED"`` (in an unbought quadrant), or a mapping
            describing a plant, weed, or animal structure occupying
            that tile.
        farmer: The ``[x, y]`` position of the main farmer on the
            board.
        hands: The ``[x, y]`` positions of each hired farm hand
            currently on the board for the current day.
        unlocked_quadrants: The subset of quadrant names (from
            ``"NW"``, ``"NE"``, ``"SW"``, ``"SE"``) this player has
            bought.
        hires_today: The number of farm hands already hired today,
            used by the market to price the next hire.
    """

    tiles: Sequence[Sequence[TileValue]]
    farmer: Sequence[int]
    hands: Sequence[Sequence[int]]
    unlocked_quadrants: Sequence[str]
    hires_today: int
