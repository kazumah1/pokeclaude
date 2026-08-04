import pytest
from pokeclaude import marketplace_client as mc


class Recorder:
    def __init__(self): self.calls = []
    def __call__(self, method, path, body=None, token=None):
        self.calls.append((method, path, body))
        return 200, {"ok": path}


@pytest.fixture
def rec(monkeypatch):
    monkeypatch.setenv("POKECLAUDE_MARKET_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(mc, "saved_token", lambda: "tok")
    r = Recorder(); monkeypatch.setattr(mc, "request_json", r); return r


def test_dormant_when_unconfigured(monkeypatch):
    monkeypatch.delenv("POKECLAUDE_MARKET_URL", raising=False)
    from pokeclaude import store
    monkeypatch.setattr(store, "load_config", lambda path=store.CONFIG_PATH: {})
    assert mc.browse() == mc.NO_SERVER
    assert mc.create_listing(1) == mc.NO_SERVER


def test_browse_hits_get_listings(rec):
    mc.browse()
    assert ("GET", "/listings", None) in rec.calls


def test_create_listing_posts(rec):
    mc.create_listing(5, note="ft charmander")
    assert ("POST", "/listings", {"item_id": 5, "note": "ft charmander"}) in rec.calls


def test_offer_posts(rec):
    mc.create_offer(3, 9)
    assert ("POST", "/offers", {"listing_id": 3, "offered_item_id": 9}) in rec.calls


def test_accept_posts_to_offer_path(rec):
    mc.accept_offer(7)
    assert ("POST", "/offers/7/accept", {}) in rec.calls


def test_cancel_posts(rec):
    mc.cancel_listing(4)
    assert ("POST", "/listings/4/cancel", {}) in rec.calls
