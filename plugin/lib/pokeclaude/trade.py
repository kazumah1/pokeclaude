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
