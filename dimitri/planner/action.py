"""Represents a single candidate game action considered by the Planner.

An Action describes one possible move Dimitri could make — what kind of
action it is, what it targets, and how many units it involves. It is a
representation only: it carries no execution logic, no validation
against game rules, and no judgement about whether it is a good idea.
Choosing among actions belongs to the Executive downstream.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    """An immutable description of one possible game action.

    Attributes:
        action_type: The kind of action (e.g. "BUY", "SELL", "PLANT").
        target: The resource or crop the action applies to, if any.
        quantity: The number of units the action involves.
    """

    action_type: str
    target: str | None = None
    quantity: int = 1
