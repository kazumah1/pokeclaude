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
