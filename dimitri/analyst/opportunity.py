"""Represents something Dimitri could potentially pursue.

An Opportunity answers "what could we pursue?" — growing a crop,
raising animals, trading on the market, buying land, or simply holding
cash. It is the top of Dimitri's planning hierarchy:

    Opportunity  what could we pursue?
        -> Plan  what sequence of actions would pursue it?
        -> Action  what do we execute right now?

An Opportunity is descriptive only. It is not a decision and carries no
recommendation, score, probability, evaluation, or executable action.
Whether an opportunity exists in a given GameState, and whether it is
worth pursuing, are separate questions answered downstream; this module
answers neither.

Opportunity lives with the Analyst because identifying which
opportunities a GameState offers will be the Analyst's job. The
Analyst does not produce Opportunities yet.
"""

from dataclasses import dataclass
from enum import Enum


class OpportunityKind(Enum):
    """The kinds of thing Dimitri could pursue."""

    WHEAT_PRODUCTION = "WHEAT_PRODUCTION"
    CARROT_PRODUCTION = "CARROT_PRODUCTION"
    TOMATO_PRODUCTION = "TOMATO_PRODUCTION"
    STRAWBERRY_PRODUCTION = "STRAWBERRY_PRODUCTION"
    MELON_PRODUCTION = "MELON_PRODUCTION"
    ANIMAL_PRODUCTION = "ANIMAL_PRODUCTION"
    MARKET_TRADE = "MARKET_TRADE"
    LAND_EXPANSION = "LAND_EXPANSION"
    HOLD_CASH = "HOLD_CASH"


@dataclass(frozen=True)
class Opportunity:
    """An immutable description of one thing Dimitri could pursue.

    Attributes:
        kind: What kind of opportunity this is.
    """

    kind: OpportunityKind

    def __post_init__(self) -> None:
        """Reject a kind that is not an OpportunityKind.

        Raises:
            TypeError: If ``kind`` is not an OpportunityKind. A kind's
                name can be converted with ``OpportunityKind(name)``,
                which raises ValueError for an unknown name.
        """
        if not isinstance(self.kind, OpportunityKind):
            raise TypeError(
                f"Opportunity.kind must be an OpportunityKind, "
                f"got {type(self.kind).__name__}"
            )
