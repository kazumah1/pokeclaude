import json
import os
import pytest

from pokeclaude import marketplace_client as mc
from pokeclaude import store


class FakeServer:
    """In-memory stand-in for request_json: records deposits by token, holds items."""
    def __init__(self):
        self.items = {}      # item_id -> {"species_id","name"}
        self.by_token = {}   # deposit_token -> item_id
        self.next_id = 1
        self.fail = False    # simulate transport failure

    def __call__(self, method, path, body=None, token=None):
        if self.fail:
            raise mc.MarketError("could not reach marketplace")
        if path == "/deposit":
            dt = body["deposit_token"]
            if dt in self.by_token:
                return 200, {"item_id": self.by_token[dt], "state": "held", "idempotent": True}
            iid = self.next_id; self.next_id += 1
            self.items[iid] = {"species_id": body["species_id"], "name": body["name"]}
            self.by_token[dt] = iid
            return 200, {"item_id": iid, "state": "held"}
        if path == "/withdraw":
            iid = body["item_id"]
            if iid not in self.items:
                return 409, {"error": "gone"}
            it = self.items.pop(iid)
            return 200, it
        raise AssertionError("unexpected path %s" % path)


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setenv("POKECLAUDE_MARKET_URL", "http://127.0.0.1:1")  # configured
    monkeypatch.setattr(mc, "saved_token", lambda: "tok")
    fs = FakeServer()
    monkeypatch.setattr(mc, "request_json", fs)
    return fs


def _give(sid, n):
    for _ in range(n):
        store.record_catch(sid, path=store.DEX_PATH)


def test_deposit_removes_local_then_posts(fake):
    _give(25, 2)
    out = mc.deposit("pikachu")
    assert out["deposited"]["species_id"] == 25
    # local copy decremented 2 -> 1
    assert store.load(path=store.DEX_PATH)["caught"]["25"]["count"] == 1
    # server holds it
    assert out["item_id"] in fake.items


def test_deposit_unknown_or_unowned_no_mutation(fake):
    out = mc.deposit("pikachu")   # not owned
    assert "error" in out
    assert 25 not in store.caught_ids(path=store.DEX_PATH)


def test_deposit_transport_failure_leaves_pending_and_reconciles(fake):
    # NOTE: the brief's final assertion asserted `25 in caught_ids` after a
    # reconcile whose re-POST LANDS on the server. That contradicts both the
    # binding constraint ("lands -> clear; refused -> restore") and the never-dupe
    # invariant: when the original deposit actually persisted but the response was
    # lost, the idempotent re-POST returns the SAME item, so restoring locally would
    # put the Pokemon in BOTH the local dex and the server vault (duplication). The
    # invariant-safe outcome is: the deposit RESOLVES on the server, pending clears,
    # and it lives in exactly one place. Assertion corrected accordingly.
    _give(25, 1)
    fake.fail = True
    out = mc.deposit("pikachu")
    assert out.get("pending")                       # reported as pending
    assert 25 not in store.caught_ids(path=store.DEX_PATH)  # copy already left (safe direction)
    # server recovers; reconcile: idempotent re-POST lands -> deposit completes on
    # the server (never restored locally, or the copy would exist in two places)
    fake.fail = False
    rec = mc.reconcile()
    assert rec["pending_remaining"] == 0                   # pending resolved
    assert any("item_id" in r for r in rec["reconciled"])  # landed on the server
    assert 25 not in store.caught_ids(path=store.DEX_PATH)  # exactly one place, nothing lost
    assert any(it["species_id"] == 25 for it in fake.items.values())  # held in the vault


def test_reconcile_server_refusal_restores_local(fake, monkeypatch):
    # Added coverage for the never-strand direction: if the server actively REFUSES
    # a pending deposit (non-200, escrow will never happen), reconcile restores the
    # local copy so the Pokemon is not lost. This branch is otherwise untested.
    _give(25, 1)
    # copy already left locally + a pending op recorded (as after a transport failure)
    store.transaction(lambda d: mc._decrement_one(d, "25"), path=store.DEX_PATH)
    mc._add_pending({"deposit_token": "refuse0000000000", "species_id": 25, "name": "pikachu"})
    assert 25 not in store.caught_ids(path=store.DEX_PATH)

    def refusing(method, path, body=None, token=None):
        assert path == "/deposit"
        return 403, {"error": "suspended"}

    monkeypatch.setattr(mc, "request_json", refusing)
    rec = mc.reconcile()
    assert 25 in store.caught_ids(path=store.DEX_PATH)      # restored, nothing stranded
    assert not fake.items                                   # never escrowed
    assert any("restored" in r for r in rec["reconciled"])
    assert rec["pending_remaining"] == 0


def test_withdraw_server_first_then_local_recatch(fake):
    # seed a server-side item to withdraw
    _give(25, 1)
    dep = mc.deposit("pikachu")
    iid = dep["item_id"]
    out = mc.withdraw(iid)
    assert out["withdrawn"]["species_id"] == 25
    assert 25 in store.caught_ids(path=store.DEX_PATH)      # back in the dex
    assert iid not in fake.items                            # server released it


def test_never_in_two_places_after_deposit(fake):
    _give(25, 1)
    dep = mc.deposit("pikachu")
    # after a successful deposit: gone locally, present on server — never both
    assert 25 not in store.caught_ids(path=store.DEX_PATH)
    assert dep["item_id"] in fake.items
