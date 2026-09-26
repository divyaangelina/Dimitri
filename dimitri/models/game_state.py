"""Central data model representing Dimitri's understanding of the game.

GameState is the single source of truth shared by every Dimitri module
(Observer, Analyst, Planner, Executive, and Operator). It captures a
snapshot of factual, observed information at a single point in time and
nothing more.

GameState stores facts only. It never performs analysis, evaluation, or
decision-making of any kind — no ROI calculations, no bottleneck detection,
no investment ranking, no market predictions, no planning, and no action
selection. Those responsibilities belong to other modules (primarily the
Analyst, Planner, and Executive). GameState exists purely to be read.

Because it is a frozen dataclass, a GameState instance cannot be mutated
after creation. Each new game turn is represented by constructing a new
GameState rather than modifying an existing one.
"""

from dataclasses import dataclass

from dimitri.models.market import Market
from dimitri.models.opponent import Opponent
from dimitri.models.player import Player


@dataclass(frozen=True)
class GameState:
    """An immutable snapshot of Dimitri's known facts about the game.

    GameState is a pure data container. It composes the other core
    models (Player, Opponent, Market) into a single object that can be
    passed between modules, inspected, and serialized for debugging or
    testing.

    GameState is responsible only for holding facts as observed at a
    given day and hour. It is explicitly not responsible for
    interpreting those facts, calculating derived metrics, or making
    any decisions — those responsibilities belong to the Analyst,
    Planner, and Executive modules downstream.

    Attributes:
        day: The current in-game day, as reported by the observation.
        hour: The current turn within the day, as reported by the
            observation.
        player: Dimitri's own player state (money, inventory, seeds,
            and farm).
        opponent: The opposing player's publicly observable state
            (money and farm; their private shed and seeds are never
            visible to Dimitri).
        market: The shared market state (prices and inventory).
        raw_observation: The unmodified observation dict from the Kaggle
            environment, retained for debugging, traceability, and to
            support future fields without requiring re-parsing.
    """

    day: int
    hour: int
    player: Player
    opponent: Opponent
    market: Market
    raw_observation: dict
