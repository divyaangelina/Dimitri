"""Fixed game constants shared across Dimitri's modules.

Values here mirror the Kaggriculture environment's defaults so that
calculations reference a single named source rather than hardcoding
numbers inline.
"""

SEASON_LENGTH_DAYS = 30
"""The number of in-game days in one season.

The Kaggriculture environment runs 24 turns per day for 30 days (720
turns) by default. Days are zero-indexed in the observation, so the
final day of the season is ``SEASON_LENGTH_DAYS - 1``.
"""
