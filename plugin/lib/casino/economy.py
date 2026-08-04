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


def _resolve_species(target, meta):
    """Map a user-supplied name or dex number to a species id (mirrors
    pokeclaude's release.resolve)."""
    t = str(target).strip().lower()
    if t.isdigit():
        return int(t) if str(int(t)) in meta else None
    for k, v in meta.items():
        if (v.get("name") or "").lower() == t:
            return int(k)
    return None


def _needs_confirm(name):
    return {"needs_confirm": True,
            "msg": "Selling your last %s removes it from the Pokedex. "
                   "Re-run with --confirm." % name}


def sell_species(name_or_id, confirm):
    """Sell one copy of a species for its rarity price, crediting the bankroll.

    Decrements the GLOBAL owned count and the global catch tally via pokeclaude's
    own transaction/lock. Selling the last copy removes the species and requires
    confirm, mirroring pokeclaude's release --confirm safety; that gate is
    enforced INSIDE the lock, so a concurrent sale that drops the count to its
    last copy cannot slip an unconfirmed removal through.
    """
    meta = load_meta()
    sid = _resolve_species(name_or_id, meta)
    if sid is None:
        return {"error": "unknown pokemon: %s" % name_or_id}
    key = str(sid)
    name = (meta.get(key) or {}).get("name", "#%d" % sid)

    # Fast, lock-free pre-checks for the common case. The AUTHORITATIVE last-copy
    # gate runs inside the transaction below (a concurrent 2->1 sale between here
    # and the lock cannot sell a last copy without --confirm).
    dex = dex_store.load(path=dex_store.DEX_PATH)
    entry = (dex.get("caught") or {}).get(key)
    count = entry.get("count", 0) if isinstance(entry, dict) else 0
    if count <= 0:
        return {"error": "you don't own %s" % name}
    if count == 1 and not confirm:
        return _needs_confirm(name)

    tier = encounter.rarity_tier(sid)
    price = PRICE[tier]

    def _decrement(d):
        caught = d.get("caught") or {}
        e = caught.get(key)
        if not isinstance(e, dict):
            return None  # vanished under a concurrent sale
        cur = e.get("count", 1)
        if cur <= 0:
            return None  # nothing left to sell
        if cur == 1 and not confirm:
            return "needs_confirm"  # raced down to the last copy -> gate it, no mutation
        e["count"] = cur - 1
        d["totals"]["catches"] = max(0, d.get("totals", {}).get("catches", 0) - 1)
        if e["count"] <= 0:
            del caught[key]
        return e.get("count", 0)

    new_count = dex_store.transaction(_decrement, path=dex_store.DEX_PATH)
    if new_count is None:
        return {"error": "could not update the Pokedex — nothing was sold"}
    if new_count == "needs_confirm":
        return _needs_confirm(name)

    st = casino_store.transaction(lambda s: s.__setitem__("bankroll",
                                                          s["bankroll"] + price))
    if st is None:
        st = casino_store.load()
    return {"sold": {"name": name, "tier": tier, "price": price},
            "bankroll": st["bankroll"]}
