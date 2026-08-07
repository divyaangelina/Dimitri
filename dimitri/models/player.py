"""Represents Dimitri's own observable state within the game.

Player is the canonical record of what Dimitri currently owns and
controls at a single point in time. It is composed into GameState
alongside Market and Inventory to form Dimitri's complete picture of
the world.

Like GameState, Player stores facts only. It never performs reasoning,
evaluation, or decision-making — no ROI calculations, no bottleneck
detection, no investment ranking, no income prediction, and no action
selection. Those responsibilities belong to the Analyst, Planner, and
Executive modules downstream. Player exists purely to be read.

Because it is a frozen dataclass, a Player instance cannot be mutated
after construction. Each new observation produces a new Player rather
than modifying an existing one.
"""

from dataclasses import dataclass

from dimitri.models.inventory import Inventory


@dataclass(frozen=True)
class Player:
    """An immutable snapshot of Dimitri's own ownership state.

    Player is a pure data container. It represents ownership — what
    Dimitri currently has — rather than behavior or intent. It composes
    the Inventory model rather than flattening shed contents into
    primitive fields, keeping related data grouped together.

    Player is responsible only for holding facts about Dimitri's state
    as observed at a given moment. It is explicitly not responsible for
    interpreting those facts, calculating derived metrics, or making
    any decisions — those responsibilities belong to the Analyst,
    Planner, and Executive modules, and remain fully independent of
    this model.

    Attributes:
        player_id: Dimitri's player index in the game (0 or 1).
        money: Dimitri's current bank balance, in coins.
        inventory: Dimitri's private shed/inventory contents.
    """

    player_id: int
    money: int
    inventory: Inventory
