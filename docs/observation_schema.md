Observation

day

hour

player

farms

private

market

town

## Observed fields and where Dimitri keeps them

Sources of truth: the sample observation (`tests/sample_observation.json`),
the environment's `kaggriculture.json` observation spec, and
`_new_private`, `_new_town`, `_do_hire`, `_farmer_inventory` and
`_end_of_day` in `kaggriculture.py`.

Visibility: *shared* means both players see the same value. *Public*
means per-player, but visible to both players. *Private* means only
this player sees it.

| Raw field | Visibility | Raw shape | Dimitri model |
| --- | --- | --- | --- |
| `step` | shared | int, 0-indexed episode turn (supplied by the kaggle-environments framework) | `GameState.step` |
| `day` | shared | int | `GameState.day` |
| `hour` | shared | int | `GameState.hour` |
| `player` | — | int, this agent's index | `Player.player_id` (opponent index is the other entry of `farms`) |
| `farms[i]` | public | farm dict (see below) | `Player.farm` / `Opponent.farm`, `money` → `Player.money` / `Opponent.money` |
| `private.shed` | private | `{item: int}` | `Player.inventory` (`Inventory`) |
| `private.seeds` | private | `{crop: int}` | `Player.seeds` |
| `private.inventories` | private | list of `{item: int}` | `Player.unit_inventories` (tuple of `Inventory`) |
| `market.inventory` | shared | `{product: int}` | `Market.inventory` |
| `market.prices` | shared | `{product: int}` | `Market.prices` |
| `town.unlocked_shops` | shared | list of shop-name strings | `GameState.town` (`Town.unlocked_shops`, tuple of str) |

### `private.inventories`

- This lists the items each unit carries in the field:
  `[main_farmer_inv, hand1_inv, ...]`. Index 0 is always the main
  farmer, and index `i >= 1` is the hand at `farms[player].hands[i - 1]`.
- Each entry is an `{item: count}` dict. It can hold produce, animals,
  or fertilizer, but never seeds. The environment deletes a key when
  its count reaches 0, so an empty unit is `{}`.
- It starts as `[{}]`. `HIRE` appends `{}`, and end of day drops every
  unit's items into the shed and resets it to `[{}]`.
- This is separate from `private.shed`. Dimitri keeps the shed as
  `Player.inventory` and the unit inventories as
  `Player.unit_inventories`.

### `town.unlocked_shops`

- A list of shop names such as `"BAKERY"` or `"PET_CAFE"`, in unlock
  order. It is empty at the start of the game. The environment appends
  one shop every `townShopUnlockInterval` days and never removes one.
- The observation contains only the shop names. Which products a shop
  demands is not part of the observation, so Dimitri does not store it.

### Parser and validator behavior for these fields

- A missing `step`, `town`, `town.unlocked_shops`, or
  `private.inventories` raises `ParseError`.
- `step` must be an int (bools are rejected). `unlocked_shops` must be
  a list of strings. `inventories` must be a list of mappings.
  Anything else raises `ParseError`.
- Unit inventory counts are checked by the Validator in the same way
  as the shed. Keys must be strings and counts must be ints, otherwise
  it raises `ValidationError`.
- All parsed values are copied into tuples and frozen dataclasses, so
  they share no mutable state with the observation.

### Present but not modeled

These fields are kept only in `GameState.raw_observation`:

- `remainingOverageTime`: the kaggle-environments framework's
  remaining overage time budget for the agent. It is not game state.
- `market.params`: this only appears when the environment is
  configured with market-price overrides (`_new_market`). It is absent
  under the default configuration and in the sample observation.

The framework stores `step` only on player 0's stored environment
state. Every observation delivered to an agent, for either player,
does include `step`.


## Farm tiles

Source of truth: the installed Kaggriculture environment
(`kaggle_environments/envs/kaggriculture/kaggriculture.py`, v1.32.4 —
`_new_farm`, `_new_plant`, `_new_animal`, and the `DIG` / `BUILD_COOP` /
`BUILD_PASTURE` / decay / refresh / weed-spawn handlers).

Each entry in `farms` has a `tiles` grid indexed `tiles[y][x]`. Every
tile is exactly one of the values below. No other tile values or tile
fields are written by the environment.

### Observed values (facts from Kaggriculture)

| Tile | Raw value | Fields |
| --- | --- | --- |
| Empty unlocked | `None` | — |
| Locked | `"LOCKED"` | — (tile is in a quadrant the player has not bought) |
| Plant | dict, `kind == "PLANT"` | `kind`, `crop`, `planted_day`, `watered_today`, `consecutive_unwatered`, `yield_units`, `max_lifespan_step`, `fertilized_until_day` |
| Weed | dict, `kind == "WEED"` | `kind` |
| Empty structure | dict, `kind` is `"COOP"` or `"PASTURE"`, no `animal` key | `kind` |
| Occupied animal structure | dict, `kind` is `"COOP"` or `"PASTURE"`, has `animal` key | `kind`, `animal`, `placed_day`, `yield_units`, `consecutive_unfed`, `fed_today`, `cared_today`, `fertilizer_available`, `pending_care_bonus` |

Plant fields:

| Field | Type | Meaning (as set by the environment) |
| --- | --- | --- |
| `kind` | str | Always `"PLANT"`. |
| `crop` | str | Crop planted, e.g. `"WHEAT"`. |
| `planted_day` | int | Day the crop was planted. |
| `watered_today` | bool | Whether the plant has been watered today. |
| `consecutive_unwatered` | int | Consecutive end-of-day refreshes without water. Starts at `1` (the planting day counts as unwatered). |
| `yield_units` | int | Units currently available to harvest. |
| `max_lifespan_step` | int | Step at which decay begins, or `-1` when not yet set (ongoing crops until their production cap). |
| `fertilized_until_day` | int | Last day (inclusive) the fertilizer bonus applies, or `-1` if never fertilized. |

Occupied animal structure fields:

| Field | Type | Meaning (as set by the environment) |
| --- | --- | --- |
| `kind` | str | Structure the animal lives on: `"COOP"` or `"PASTURE"`. |
| `animal` | str | Animal on the tile, e.g. `"GOOSE"`, `"COW"`, `"SHEEP"`. |
| `placed_day` | int | Day the animal was placed. |
| `yield_units` | int | Units of animal product currently available to harvest. |
| `consecutive_unfed` | int | Consecutive end-of-day refreshes without feed. |
| `fed_today` | bool | Whether the animal has been fed today. |
| `cared_today` | bool | Whether the animal has been cared for today. |
| `fertilizer_available` | bool | Whether a unit of fertilizer is available to collect. |
| `pending_care_bonus` | int | Banked care bonus awaiting the next scheduled production. |

When an animal escapes, the environment replaces the tile with an
empty structure dict (`{"kind": <structure>}`).

### Dimitri's representation (interpretation by Dimitri)

The parser (`dimitri/observer/parser.py`) translates each tile into a
`TileValue` (`dimitri/models/farm.py`). The models live in
`dimitri/models/tile.py`.

| Raw tile | Parsed value |
| --- | --- |
| `None` | `None` (unchanged) |
| `"LOCKED"` | `"LOCKED"` (unchanged) |
| `kind == "PLANT"` | `PlantTile` |
| `kind == "WEED"` | `WeedTile` |
| `kind` in `COOP`/`PASTURE`, no `animal` key | `StructureTile(structure=kind)` |
| `kind` in `COOP`/`PASTURE`, has `animal` key | `AnimalTile(structure=kind, ...)` |

These are the only interpretations Dimitri makes:

- The choice of model class is based on `kind` and on whether the
  `animal` key is present.
- The `kind` key is not stored as a field. It is implied by the class,
  or kept as `structure` on `StructureTile` and `AnimalTile`.
- Every other model field has the same name and value as the observed
  key. No fields are derived, defaulted, or added.

### Parser behavior

- **Malformed or unknown tiles raise `ParseError`.** This happens when
  a tile is not `None`, not `"LOCKED"`, and not a dict. It also happens
  for a dict with no `kind` or an unrecognized `kind`, a missing
  required field, or a field of the wrong type. An int field rejects
  bools, and a bool field rejects ints. A `tiles` grid or row that is
  not a list also raises `ParseError`.
- **Extra keys are ignored.** Keys beyond those listed above are not
  copied into the models.
- **Parsed tile grids are immutable.** `Farm.tiles` from the parser is
  a tuple of tuples, and each tile model is a frozen dataclass. Parsed
  tiles share no mutable state with the observation.
- **`GameState.raw_observation` preserves the original observation.**
  The parser does not modify the observation dict, and it is kept on
  the `GameState` unchanged, including the raw tile dicts and any extra
  keys.
