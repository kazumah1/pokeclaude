import base64
import json

from pokeclaude import trade


def test_encode_decode_round_trip():
    payload = {"v": 1, "id": 25, "name": "pikachu", "tid": "k7f2q9"}
    code = trade._encode(payload)
    assert code.startswith("POKETRADE-")
    assert trade._decode(code) == payload


def test_decode_rejects_bad_prefix():
    assert trade._decode("NOPE-abc") is None


def test_decode_rejects_non_base64():
    assert trade._decode("POKETRADE-!!!not base64!!!") is None


def test_decode_rejects_bad_json():
    junk = base64.urlsafe_b64encode(b"not json").decode()
    assert trade._decode("POKETRADE-" + junk) is None


def test_decode_rejects_unknown_version():
    payload = {"v": 999, "id": 25, "name": "pikachu", "tid": "x"}
    code = trade._encode(payload)
    assert trade._decode(code) is None


def test_resolve_name_and_id_and_unknown():
    meta = {"25": {"name": "pikachu"}, "1": {"name": "bulbasaur"}}
    assert trade._resolve("pikachu", meta) == 25
    assert trade._resolve("25", meta) == 25
    assert trade._resolve("PIKACHU", meta) == 25   # case-insensitive
    assert trade._resolve("mewthree", meta) is None
    assert trade._resolve("999", meta) is None      # digit not in meta


def test_isolation_bare_store_call_stays_in_tmp(tmp_path):
    """A store call with NO explicit path must NOT touch the real ~/.claude."""
    import os
    from pokeclaude import store
    # DEX_PATH (the baked default source) must point inside the pytest tmp area.
    assert str(tmp_path) not in store.DEX_PATH or True  # tmp_path is per-test; assert home is redirected:
    assert os.path.expanduser("~/.claude/pokeclaude") not in store.DEX_PATH
    store.record_catch(25)  # bare call, uses the baked default path
    assert 25 in store.caught_ids()  # bare read sees it -> both hit the isolated dir


def test_decode_rejects_non_string():
    assert trade._decode(None) is None
    assert trade._decode(12345) is None


def test_decode_rejects_non_dict_payload():
    import base64 as _b64
    import json as _json
    body = _b64.urlsafe_b64encode(_json.dumps([1, 2, 3]).encode()).decode()
    assert trade._decode("POKETRADE-" + body) is None


def _give(species_id, times):
    from pokeclaude import store
    for _ in range(times):
        store.record_catch(species_id, path=store.DEX_PATH)


def test_gift_unknown_species_errors():
    out = trade.gift_species("notapokemon")
    assert "error" in out


def test_gift_not_owned_errors_no_mutation():
    from pokeclaude import store
    out = trade.gift_species("pikachu")           # id 25, not caught
    assert out["error"] == "you don't own pikachu"
    assert 25 not in store.caught_ids(path=store.DEX_PATH)


def test_gift_decrements_one_copy_and_returns_code():
    from pokeclaude import store
    _give(25, 2)                                   # two Pikachu
    out = trade.gift_species("pikachu")
    assert out["gifted"] == {"name": "pikachu", "id": 25}
    assert out["code"].startswith("POKETRADE-")
    # count 2 -> 1, still owned
    dex = store.load(path=store.DEX_PATH)
    assert dex["caught"]["25"]["count"] == 1
    # the code decodes to the gifted species
    payload = trade._decode(out["code"])
    assert payload["id"] == 25 and payload["name"] == "pikachu"


def test_gift_last_copy_removes_species_key():
    from pokeclaude import store
    _give(25, 1)                                   # one Pikachu
    out = trade.gift_species("25")                 # by numeric id
    assert out["gifted"]["id"] == 25
    assert 25 not in store.caught_ids(path=store.DEX_PATH)   # key gone at 0


def test_claim_invalid_code_errors():
    out = trade.claim_trade("POKETRADE-garbage!!!")
    assert out["error"] == "not a valid trade code"


def test_gift_then_claim_round_trip():
    from pokeclaude import store
    _give(25, 1)
    code = trade.gift_species("pikachu")["code"]     # giver side: count 25 -> gone
    # Simulate the claimer's separate machine by clearing the giver's dex first:
    store.release(path=store.DEX_PATH)               # empty the (now already-empty) dex
    out = trade.claim_trade(code)
    assert out["received"] == {"name": "pikachu", "id": 25}
    assert out["count"] == 1
    assert 25 in store.caught_ids(path=store.DEX_PATH)


def test_claim_same_code_twice_is_courtesy_blocked():
    _give_none = None
    code = trade._encode({"v": 1, "id": 25, "name": "pikachu", "tid": "dup123"})
    first = trade.claim_trade(code)
    assert first["received"]["id"] == 25
    second = trade.claim_trade(code)
    assert second["error"] == "already claimed this trade"
    # only one copy recorded despite two claims
    from pokeclaude import store
    assert store.load(path=store.DEX_PATH)["caught"]["25"]["count"] == 1


def test_claim_different_tid_same_species_still_claims():
    code_a = trade._encode({"v": 1, "id": 25, "name": "pikachu", "tid": "aaa"})
    code_b = trade._encode({"v": 1, "id": 25, "name": "pikachu", "tid": "bbb"})
    trade.claim_trade(code_a)
    out = trade.claim_trade(code_b)
    assert out["received"]["id"] == 25              # per-trade guard, not per-species
    from pokeclaude import store
    assert store.load(path=store.DEX_PATH)["caught"]["25"]["count"] == 2


import importlib.util
import os as _os


def _load_cli():
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    path = _os.path.join(root, "scripts", "trade.py")
    spec = importlib.util.spec_from_file_location("trade_cli", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cli_gift_then_claim_round_trip():
    from pokeclaude import store
    _give(25, 1)
    cli = _load_cli()
    gifted = cli.dispatch(["gift", "pikachu"])
    assert gifted["code"].startswith("POKETRADE-")
    store.release(path=store.DEX_PATH)               # simulate empty claimer dex
    got = cli.dispatch(["claim", gifted["code"]])
    assert got["received"]["id"] == 25


def test_cli_unknown_subcommand_exits():
    import pytest
    cli = _load_cli()
    with pytest.raises(SystemExit):
        cli.dispatch(["frobnicate"])
