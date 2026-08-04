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
            return r.status, json.loads(r.read().decode("utf-8"))
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
