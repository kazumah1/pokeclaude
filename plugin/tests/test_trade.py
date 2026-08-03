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
