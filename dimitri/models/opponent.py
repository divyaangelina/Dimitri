"""Represents the publicly observable state of the opposing player.

Opponent mirrors Player, but only for what the rules document says is
actually visible about the other side of the match: player identity,
bank balance, and farm layout. It is composed into GameState alongside
Player and Market.

Opponent deliberately excludes anything the observation itself does
not expose about the opponent. The raw observation is explicit that
"opponent's private state is not visible" — there is no opponent shed,
seeds, or per-unit inventory to parse, so Opponent has no Inventory
field the way Player does. Adding one would misrepresent data Dimitri
was never given.

Like the other models in this package, Opponent stores facts only. It
never performs reasoning, evaluation, or decision-making — no threat
assessment, no behavior prediction, no strategic inference. Those
responsibilities belong to the Analyst, Planner, and Executive modules
downstream. Opponent exists purely to be read.

Because it is a frozen dataclass, an Opponent instance cannot be
mutated after construction. Each new observation produces a new
Opponent rather than modifying an existing one.
"""

from dataclasses import dataclass

from dimitri.models.farm import Farm


@dataclass(frozen=True)
class Opponent:
    """An immutable snapshot of the opposing player's public state.

    Opponent is a pure data container. It holds only what the
    observation actually reveals about the other player — their
    identity, money, and farm layout — and nothing about their private
    shed or seeds, which the environment never discloses to Dimitri.

    Opponent is responsible only for holding these facts as observed
    at a given moment. It is explicitly not responsible for
    interpreting them, predicting the opponent's behavior, or making
    any decisions — those responsibilities belong to the Analyst,
    Planner, and Executive modules, and remain fully independent of
    this model.

    Attributes:
        player_id: The opponent's player index in the game (0 or 1).
        money: The opponent's current bank balance, in coins, which is
            public information visible to both players.
        farm: The opponent's farm board layout, which is likewise
            public information.
    """

    player_id: int
    money: int
    farm: Farm
