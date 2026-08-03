"""One-way Pokemon trading for pokeclaude.

A `gift` removes one copy of a species from the giver's Pokedex and returns a
self-contained text code (`POKETRADE-<base64url>`); a `claim` on another machine
decodes that code and records the species into the claimer's Pokedex. No server,
no accounts, no signatures: the code is plain data pasted through whatever chat
the users already have.

Trust model: friends-won't-cheat. The giver's side is enforced (the copy leaves
their Pokedex before the code exists). The receiver's side is honest-by-convention
— a claimed-trade id (`tid`) is recorded locally so the SAME code cannot be
claimed twice on the SAME machine, but a code is plain text and CANNOT be stopped
from being forwarded to different people. That limitation is accepted and
documented; truly preventing it needs shared state (a server), which v1 rejects
for zero-setup simplicity.
"""
import base64
import json
import os
import random

from pokeclaude import store

CODE_PREFIX = "POKETRADE-"
FORMAT_VERSION = 1
_TID_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def _encode(payload):
    """dict -> 'POKETRADE-<base64url>' (compact, url-safe, unpadded-safe)."""
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return CODE_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii")


def _decode(code):
    """'POKETRADE-<base64url>' -> payload dict, or None if the code is not a
    valid, understood trade code. Never raises."""
    if not isinstance(code, str) or not code.startswith(CODE_PREFIX):
        return None
    body = code[len(CODE_PREFIX):].strip()
    try:
        raw = base64.urlsafe_b64decode(body.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or payload.get("v") != FORMAT_VERSION:
        return None
    return payload


def _resolve(target, meta):
    """Map a user-supplied name or dex number to a species id (mirrors
    pokeclaude's release.resolve). Ported, not imported: resolve lives in a
    script, not a lib module."""
    t = str(target).strip().lower()
    if t.isdigit():
        return int(t) if str(int(t)) in meta else None
    for k, v in meta.items():
        if (v.get("name") or "").lower() == t:
            return int(k)
    return None


def _new_tid():
    """A short random trade id. Only purpose: the local replay-courtesy in
    claim_trade. NOT a security token."""
    return "".join(random.choice(_TID_ALPHABET) for _ in range(8))


_HERE = os.path.dirname(os.path.abspath(__file__))
# trade.py is plugin/lib/pokeclaude/trade.py -> assets at plugin/assets/pokemon.json
META_PATH = os.path.join(_HERE, "..", "..", "assets", "pokemon.json")


def load_meta():
    try:
        with open(META_PATH) as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return {}


def _decrement_one(dex, key):
    """Remove ONE copy of species `key` from the dex in place. Returns the new
    count (0 means the species key was deleted), or None if the species is not
    present. Must never raise (runs inside store.transaction, which does not
    catch)."""
    caught = dex.get("caught") or {}
    entry = caught.get(key)
    if not isinstance(entry, dict):
        return None
    cur = entry.get("count", 1)
    if cur <= 0:
        return None
    entry["count"] = cur - 1
    dex["totals"]["catches"] = max(0, dex.get("totals", {}).get("catches", 0) - 1)
    if entry["count"] <= 0:
        del caught[key]
    return entry.get("count", 0)


def gift_species(name_or_id):
    """Remove one owned copy of a species and return a shareable trade code."""
    meta = load_meta()
    sid = _resolve(name_or_id, meta)
    if sid is None:
        return {"error": "unknown pokemon: %s" % name_or_id}
    key = str(sid)
    name = (meta.get(key) or {}).get("name", "#%d" % sid)

    dex = store.load(path=store.DEX_PATH)
    entry = (dex.get("caught") or {}).get(key)
    count = entry.get("count", 0) if isinstance(entry, dict) else 0
    if count <= 0:
        return {"error": "you don't own %s" % name}

    new_count = store.transaction(lambda d: _decrement_one(d, key), path=store.DEX_PATH)
    if new_count is None:
        return {"error": "pokedex busy — nothing was gifted"}

    code = _encode({"v": FORMAT_VERSION, "id": sid, "name": name, "tid": _new_tid()})
    return {"gifted": {"name": name, "id": sid}, "code": code,
            "msg": "Gifted %s — its copy left your Pokedex. Send this code to a "
                   "friend, who runs: trade claim <code>." % name}
