"""The bridge between the casino and the Pokedex.

The ONLY module that imports both sides. A casino win grants a Pokemon (rarity
scaling with how big the win was); selling a Pokemon credits the casino bankroll.
Both stores are mutated only under their own locks, sequenced here, never held at
once.

Path discipline: pokeclaude's store bakes DEX_PATH into `path=` default args at
import, so we ALWAYS pass path=dex_store.DEX_PATH explicitly (read live at call
time -> correct in production, monkeypatchable in tests).
"""
import json
import os

from casino import bankroll, rng, store as casino_store
from pokeclaude import encounter, store as dex_store

_HERE = os.path.dirname(os.path.abspath(__file__))
# economy.py is plugin/lib/casino/economy.py -> assets at plugin/assets/pokemon.json
META_PATH = os.path.join(_HERE, "..", "..", "assets", "pokemon.json")

# ---- tunable constants (the single block to tune) -----------------------
# Rarity tier from the win multiple (net winnings / amount staked this action).
# mult < 2 -> COMMON; 2 <= mult < 8 -> RARE; 8 <= mult < 30 -> LEGENDARY;
# mult >= 30 -> MYTHICAL.
TIER_THRESHOLDS = (
    (2.0, "COMMON"),      # mult < 2.0
    (8.0, "RARE"),        # 2.0 <= mult < 8.0
    (30.0, "LEGENDARY"),  # 8.0 <= mult < 30.0
)
_TOP_TIER = "MYTHICAL"    # mult >= 30.0

# Sell price credited to the bankroll, keyed by the species' own rarity tier.
PRICE = {"COMMON": 500, "RARE": 2000, "LEGENDARY": 8000, "MYTHICAL": 25000}

# Empty-tier fallback: pokeclaude's roster has no RARE-band species, so a tier
# with no members falls back to the nearest populated one, ultimately COMMON,
# so a win ALWAYS grants exactly one Pokemon.
FALLBACK = {
    "MYTHICAL": ["MYTHICAL", "LEGENDARY", "RARE", "COMMON"],
    "LEGENDARY": ["LEGENDARY", "MYTHICAL", "RARE", "COMMON"],
    "RARE": ["RARE", "LEGENDARY", "MYTHICAL", "COMMON"],
    "COMMON": ["COMMON"],
}


def tier_from_multiple(net_payout, total_staked):
    """Casino rarity tier from a win's multiple. A win with nothing staked is
    COMMON (no ZeroDivision, and a zero-stake windfall is not an achievement)."""
    if total_staked <= 0:
        return "COMMON"
    mult = float(net_payout) / float(total_staked)
    for limit, label in TIER_THRESHOLDS:
        if mult < limit:
            return label
    return _TOP_TIER


def load_meta():
    try:
        with open(META_PATH) as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return {}


def roster_ids():
    return sorted(int(k) for k in load_meta())


def ids_in_tier(tier):
    """Roster species ids whose intrinsic rarity_tier equals `tier`."""
    return [pid for pid in roster_ids() if encounter.rarity_tier(pid) == tier]


def resolve_grant_tier(tier):
    """First tier in `tier`'s fallback chain that has at least one species."""
    for candidate in FALLBACK.get(tier, [tier, "COMMON"]):
        if ids_in_tier(candidate):
            return candidate
    return "COMMON"


def price_of(species_id):
    """Sell price for a species, by its own intrinsic rarity tier."""
    return PRICE[encounter.rarity_tier(int(species_id))]


def grant_on_win(net_payout, total_staked):
    """Grant one engine-rolled Pokemon for a winning hand. Returns
    {"id", "name", "tier"} (tier = the tier the WIN earned), or None if the roll
    or write could not complete. Claude never picks the species."""
    if net_payout <= 0:
        return None
    won_tier = tier_from_multiple(net_payout, total_staked)
    band = resolve_grant_tier(won_tier)
    candidates = ids_in_tier(band)
    if not candidates:
        return None
    caught = dex_store.caught_ids(path=dex_store.DEX_PATH)
    pid = encounter.pick_species(candidates, caught, seed=rng.make_seed())
    if pid is None:
        return None
    result = dex_store.record_catch(pid, path=dex_store.DEX_PATH)
    if result is None:  # dex lock unavailable -> report no grant rather than lie
        return None
    name = (load_meta().get(str(pid)) or {}).get("name", "pokemon")
    return {"id": pid, "name": name, "tier": won_tier}
