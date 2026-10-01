"""Fixed game constants shared across Dimitri's modules.

Values here mirror the Kaggriculture environment's defaults so that
calculations reference a single named source rather than hardcoding
numbers inline.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

SEASON_LENGTH_DAYS = 30
"""The number of in-game days in one season.

The Kaggriculture environment runs 24 turns per day for 30 days (720
turns) by default. Days are zero-indexed in the observation, so the
final day of the season is ``SEASON_LENGTH_DAYS - 1``.
"""

TURNS_PER_DAY = 24
"""The number of turns in one in-game day (environment ``turnsPerDay`` default)."""

LAST_ACTION_STEP = SEASON_LENGTH_DAYS * TURNS_PER_DAY - 2
"""The last step whose actions the environment applies: 718 by default.

The episode's 720 steps are observed as steps 0 to 719. The agent acts on
steps 0 to 718, and the final observation, step 719, carries the season's
closing bank money, which is the player's reward.
"""


@dataclass(frozen=True)
class CropRules:
    """The fixed per-crop rules Dimitri currently models.

    Mirrors the environment's ``CROPS`` entry, as read by ``_new_plant``,
    BUY_SEED, WATER, HARVEST, and the end-of-day plant refresh.

    Attributes:
        seed_price: The fixed price of one seed of the crop, charged by
            BUY_SEED. This is the only source of seed prices in
            Dimitri. It is unrelated to the crop's market sale price.
        first_yield_day: Days after planting before the crop can be
            harvested.
        max_yield_day: Days after planting at which a one-time crop
            reaches maximum yield.
        max_yield: The most yield units a plant can hold. For an ongoing
            crop it is also the number of productions in its life.
        interval: Days between an ongoing crop's productions; 0 for a
            one-time crop, which never produces at end of day.
        ongoing: Whether the crop produces repeatedly (True) or is
            harvested once (False).
    """

    seed_price: int
    first_yield_day: int
    max_yield_day: int
    max_yield: int
    interval: int
    ongoing: bool


CROPS: Mapping[str, CropRules] = MappingProxyType(
    {
        "WHEAT": CropRules(
            seed_price=10,
            first_yield_day=2,
            max_yield_day=4,
            max_yield=6,
            interval=0,
            ongoing=False,
        ),
        "CARROT": CropRules(
            seed_price=20,
            first_yield_day=2,
            max_yield_day=3,
            max_yield=4,
            interval=0,
            ongoing=False,
        ),
        "TOMATO": CropRules(
            seed_price=50,
            first_yield_day=8,
            max_yield_day=8,
            max_yield=4,
            interval=1,
            ongoing=True,
        ),
        "STRAWBERRY": CropRules(
            seed_price=100,
            first_yield_day=10,
            max_yield_day=10,
            max_yield=4,
            interval=2,
            ongoing=True,
        ),
        "MELON": CropRules(
            seed_price=80,
            first_yield_day=10,
            max_yield_day=12,
            max_yield=6,
            interval=0,
            ongoing=False,
        ),
    }
)
"""The crops the environment accepts for PLANT and BUY_SEED, keyed by crop name.

Mirrors ``CROPS`` in the installed Kaggriculture environment.
"""

@dataclass(frozen=True)
class AnimalRules:
    """The fixed per-animal rules read by the end-of-day animal refresh.

    Mirrors the fields of the environment's ``ANIMALS`` entry that
    ``_daily_refresh_animals`` reads.

    Attributes:
        structure: The structure the animal lives on, and that remains
            if it escapes: ``"COOP"`` or ``"PASTURE"``.
        first_yield_day: Days after placement before its first
            production.
        interval: Days between productions.
        max_held: The most unharvested product the tile can hold.
    """

    structure: str
    first_yield_day: int
    interval: int
    max_held: int


ANIMALS: Mapping[str, AnimalRules] = MappingProxyType(
    {
        "GOOSE": AnimalRules("COOP", first_yield_day=4, interval=1, max_held=4),
        "COW": AnimalRules("PASTURE", first_yield_day=8, interval=2, max_held=6),
        "SHEEP": AnimalRules("PASTURE", first_yield_day=6, interval=3, max_held=6),
    }
)
"""The animals the environment models, keyed by animal name.

Mirrors ``ANIMALS`` in the installed Kaggriculture environment.
"""

SHOPS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "BAKERY": ("EGG", "WHEAT"),
        "PIZZA_SHOP": ("MILK", "TOMATO", "WHEAT"),
        "BRUNCH_SPOT": ("EGG", "WHEAT", "STRAWBERRY"),
        "YARN_STORE": ("WOOL",),
        "ICE_CREAM_SHOP": ("STRAWBERRY", "MILK", "WHEAT"),
        "PET_CAFE": ("CARROT",),
        "SMOOTHIE_SHOP": ("STRAWBERRY", "MILK"),
        "FARMERS_MARKET": ("WHEAT", "CARROT", "TOMATO", "STRAWBERRY"),
    }
)
"""The products each town shop consumes from the market, keyed by shop.

Mirrors ``SHOPS`` in the installed Kaggriculture environment.
"""

TOWN_SHOP_SELL_INTERVAL = 4
"""Every this many steps, each unlocked shop consumes its products (``townShopSellInterval``)."""

TOWN_CENTER_SELL_INTERVAL = 12
"""Every this many steps, the town center consumes products (``townCenterSellInterval``)."""

TOWN_CENTER_DEMAND_SCHEDULE = ((20, 4), (10, 2), (0, 1))
"""``(from_day, units)`` pairs, latest first: units of each product the town center consumes.

Mirrors ``TOWN_CENTER_DEMAND_SCHEDULE`` in the installed environment.
"""

SHED_CAPACITY = 100
"""Maximum non-seed items the shed can hold (environment ``shedCapacity`` default)."""

MAX_MARKET_ORDERS_PER_TURN = 10
"""Market orders processed per player per turn (``maxMarketOrdersPerTurn`` default).

The environment silently drops any orders beyond this limit.
"""

PRODUCTS = (
    "WHEAT",
    "CARROT",
    "TOMATO",
    "STRAWBERRY",
    "MELON",
    "EGG",
    "MILK",
    "WOOL",
    "FERTILIZER",
)
"""The items the market trades. These are the only items SELL accepts."""

BUYABLE_PRODUCTS = frozenset({"WHEAT", "FERTILIZER"})
"""The only items BUY_PRODUCT accepts."""

PRICE_FLOOR = 1
"""The lowest price the market quotes. A sale at this price does not add to market inventory."""


@dataclass(frozen=True)
class PriceCurve:
    """The fixed parameters of one product's market price curve.

    Mirrors one entry of the environment's ``MARKET_PARAMS``. The
    environment's ``market_price`` turns these into a price for a given
    market inventory.
    """

    base: int
    I0: int
    T: int
    below_func: str
    below_target: float
    above_func: str
    above_target: float


MARKET_PARAMS: Mapping[str, PriceCurve] = MappingProxyType(
    {
        "WHEAT": PriceCurve(25, 10000, 400, "sqrt", 0.80, "log", 0.20),
        "CARROT": PriceCurve(35, 10000, 450, "log", 0.20, "sqrt", 0.70),
        "TOMATO": PriceCurve(60, 10000, 200, "linear", 0.40, "sqrt", 0.60),
        "STRAWBERRY": PriceCurve(120, 10000, 100, "sqrt", 0.70, "linear", 1.60),
        "MELON": PriceCurve(250, 10000, 300, "log", 0.20, "sq", 3.60),
        "EGG": PriceCurve(50, 10000, 332, "linear", 0.40, "log", 0.20),
        "MILK": PriceCurve(160, 10000, 122, "sqrt", 0.60, "linear", 1.60),
        "WOOL": PriceCurve(200, 10000, 105, "log", 0.20, "sq", 3.20),
        "FERTILIZER": PriceCurve(100, 10000, 200, "linear", 0.40, "linear", 0.40),
    }
)
"""Default market price curves, keyed by product.

Mirrors ``MARKET_PARAMS`` in the installed Kaggriculture environment.
An episode configured with ``marketParams`` overrides uses different
curves. Dimitri does not model those overrides.
"""
