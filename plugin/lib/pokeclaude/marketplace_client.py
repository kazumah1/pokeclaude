"""Client for the (self-hosted) Pokémon marketplace server.

Dormant by default: with no POKECLAUDE_MARKET_URL (env or pokeclaude config), every
operation is a no-op that returns NO_SERVER and makes no network call. The server URL
is NEVER hardcoded. This module is the only code that touches both the local Pokédex
and the remote server; the local<->server bridge (deposit/withdraw) is in a later task.
"""
import json
import os
from urllib import request, error

from pokeclaude import store

NO_SERVER = {"info": "no marketplace server configured — "
                     "set POKECLAUDE_MARKET_URL to use the marketplace"}


class MarketError(Exception):
    pass


def server_url():
    """Resolved server URL from env or config, or None if unset/invalid."""
    url = os.environ.get("POKECLAUDE_MARKET_URL")
    if not url:
        url = (store.load_config(path=store.CONFIG_PATH) or {}).get("marketplace_url")
    if not url or not isinstance(url, str):
        return None
    if not (url.startswith("http://") or url.startswith("https://")):
        return None
    return url.rstrip("/")


def configured():
    return server_url() is not None


def saved_token():
    return (store.load_config(path=store.CONFIG_PATH) or {}).get("marketplace_token")


def request_json(method, path, body=None, token=None):
    """Make an HTTP call; return (status, dict). Raises MarketError on transport failure."""
    base = server_url()
    if base is None:
        raise MarketError("no server configured")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with request.urlopen(req, timeout=10) as r:
            try:
                return r.status, json.loads(r.read().decode("utf-8"))
            except ValueError:
                raise MarketError("marketplace returned a non-JSON response")
    except error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except (ValueError, OSError):
            return e.code, {"error": "server error %d" % e.code}
    except (error.URLError, OSError):
        raise MarketError("could not reach marketplace at %s" % base)


def register(name):
    if not configured():
        return NO_SERVER
    try:
        status, out = request_json("POST", "/register", {"name": name})
    except MarketError as e:
        return {"error": str(e)}
    if status == 200 and out.get("token"):
        store.save_config({"marketplace_token": out["token"]}, path=store.CONFIG_PATH)
        return {"registered": name, "msg": "Registered as %s. Token saved." % name}
    return out


import random as _random

_HERE = os.path.dirname(os.path.abspath(__file__))
META_PATH = os.path.join(_HERE, "..", "..", "assets", "pokemon.json")
_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def _load_meta():
    try:
        with open(META_PATH) as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return {}


def _resolve(target, meta):
    t = str(target).strip().lower()
    if t.isdigit():
        return int(t) if str(int(t)) in meta else None
    for k, v in meta.items():
        if (v.get("name") or "").lower() == t:
            return int(k)
    return None


def _new_token():
    return "".join(_random.choice(_ALPHABET) for _ in range(16))


def _decrement_one(dex, key):
    """Remove ONE copy of species `key` in place; return the new count (0 = key
    deleted) or None if absent. Must never raise (runs inside store.transaction)."""
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


# --- pending-op ledger (in pokeclaude config, disposable) --------------------

def _pending():
    return (store.load_config(path=store.CONFIG_PATH) or {}).get("marketplace_pending") or []


def _set_pending(ops):
    store.save_config({"marketplace_pending": ops}, path=store.CONFIG_PATH)


def _add_pending(op):
    ops = _pending(); ops.append(op); _set_pending(ops)


def _clear_pending(deposit_token):
    _set_pending([o for o in _pending() if o.get("deposit_token") != deposit_token])


# --- deposit / withdraw ------------------------------------------------------

def deposit(name_or_id):
    if not configured():
        return NO_SERVER
    token = saved_token()
    if not token:
        return {"error": "not registered — run: marketplace register <name>"}
    meta = _load_meta()
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

    dtok = _new_token()
    # 1) remove locally FIRST (safe direction: never in both places)
    new_count = store.transaction(lambda d: _decrement_one(d, key), path=store.DEX_PATH)
    if new_count is None:
        return {"error": "pokedex busy — nothing was deposited"}
    # record the pending op so a failure can be reconciled
    _add_pending({"deposit_token": dtok, "species_id": sid, "name": name})
    # 2) tell the server
    try:
        status, out = request_json("POST", "/deposit",
                                   {"species_id": sid, "name": name, "deposit_token": dtok}, token)
    except MarketError as e:
        return {"pending": dtok, "species_id": sid, "name": name,
                "error": "%s — deposit is pending; run: marketplace reconcile" % e}
    if status == 200 and "item_id" in out:
        _clear_pending(dtok)
        return {"deposited": {"species_id": sid, "name": name}, "item_id": out["item_id"]}
    # server rejected: restore the local copy (nothing was escrowed)
    store.record_catch(sid, path=store.DEX_PATH)
    _clear_pending(dtok)
    return out if isinstance(out, dict) else {"error": "deposit failed"}


def withdraw(item_id):
    if not configured():
        return NO_SERVER
    token = saved_token()
    if not token:
        return {"error": "not registered — run: marketplace register <name>"}
    try:
        status, out = request_json("POST", "/withdraw", {"item_id": int(item_id)}, token)
    except MarketError as e:
        return {"error": str(e)}
    if status != 200 or "species_id" not in out:
        return out if isinstance(out, dict) else {"error": "withdraw failed"}
    # server released it; now re-catch locally
    store.record_catch(int(out["species_id"]), path=store.DEX_PATH)
    return {"withdrawn": {"species_id": out["species_id"], "name": out.get("name")}}


def reconcile():
    """Resolve pending deposits: ask the server whether each landed. Landed -> clear;
    not landed -> re-catch locally so nothing is lost."""
    if not configured():
        return NO_SERVER
    token = saved_token()
    resolved = []
    for op in list(_pending()):
        dtok = op["deposit_token"]
        try:
            # re-POST is idempotent: same token returns the same item if it landed,
            # or creates it now if it never did (both are 'resolved: on server').
            status, out = request_json("POST", "/deposit",
                                       {"species_id": op["species_id"], "name": op["name"],
                                        "deposit_token": dtok}, token)
        except MarketError:
            continue  # still unreachable; leave pending
        if status == 200 and "item_id" in out:
            _clear_pending(dtok)
            resolved.append({"deposit_token": dtok, "item_id": out["item_id"]})
        else:
            # server refused to accept it -> the escrow won't happen; give the copy back
            store.record_catch(int(op["species_id"]), path=store.DEX_PATH)
            _clear_pending(dtok)
            resolved.append({"deposit_token": dtok, "restored": op["species_id"]})
    return {"reconciled": resolved, "pending_remaining": len(_pending())}


# --- market commands (thin passthroughs over the server) ---------------------

def _authed_call(method, path, body=None):
    if not configured():
        return NO_SERVER
    token = saved_token()
    if not token:
        return {"error": "not registered — run: marketplace register <name>"}
    try:
        status, out = request_json(method, path, body, token)
    except MarketError as e:
        return {"error": str(e)}
    return out if isinstance(out, dict) else {"error": "unexpected response"}


def vault():
    return _authed_call("GET", "/vault")


def browse():
    return _authed_call("GET", "/listings")


def create_listing(item_id, note=None):
    body = {"item_id": int(item_id)}
    if note:
        body["note"] = note
    return _authed_call("POST", "/listings", body)


def cancel_listing(listing_id):
    return _authed_call("POST", "/listings/%d/cancel" % int(listing_id), {})


def create_offer(listing_id, offered_item_id):
    return _authed_call("POST", "/offers",
                        {"listing_id": int(listing_id), "offered_item_id": int(offered_item_id)})


def accept_offer(offer_id):
    return _authed_call("POST", "/offers/%d/accept" % int(offer_id), {})


def decline_offer(offer_id):
    return _authed_call("POST", "/offers/%d/decline" % int(offer_id), {})


def withdraw_offer(offer_id):
    return _authed_call("POST", "/offers/%d/withdraw" % int(offer_id), {})
