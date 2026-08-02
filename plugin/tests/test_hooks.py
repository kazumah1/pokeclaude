import importlib.util
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name):
    path = os.path.join(ROOT, "hooks", name)
    spec = importlib.util.spec_from_file_location(name.replace(".py", "_hook"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_render_emits_frame_for_casino_command(casino_home, monkeypatch, capsys):
    from casino import store
    store.write_frame("\x1b[38;2;1;2;3m▀\x1b[0m")
    render = _load("render.py")
    payload = {"tool_input": {"command": "python3 scripts/casino.py bj stand"},
               "tool_response": {"stdout": "{}"}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    render.main()
    out = capsys.readouterr().out
    assert "▀" in json.loads(out)["systemMessage"]


def test_render_ignores_unrelated_command(casino_home, monkeypatch, capsys):
    render = _load("render.py")
    payload = {"tool_input": {"command": "ls -la"}, "tool_response": {"stdout": ""}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    render.main()
    assert capsys.readouterr().out == ""


def test_earn_credits_once_per_turn(casino_home, monkeypatch, tmp_path):
    from casino import store
    transcript = tmp_path / "t.jsonl"
    lines = [
        {"type": "user", "uuid": "u1", "message": {"content": "hi"}},
        {"type": "assistant", "message": {"id": "m1", "usage":
            {"output_tokens": 1000, "input_tokens": 0}}},
    ]
    transcript.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    earn = _load("earn.py")
    payload = {"transcript_path": str(transcript)}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    earn.main()
    assert store.load()["bankroll"] == 10000 + 1000
    # Running again for the same turn must not double-credit.
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    earn.main()
    assert store.load()["bankroll"] == 10000 + 1000


def test_render_emits_large_holdem_showdown_frame(casino_home, monkeypatch, capsys):
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.join(ROOT, "lib"))
    from casino import store, render_table, cards, holdem
    C = cards.Card
    st = holdem.start_game(10000, 7, num_opponents=2)
    board = [C(14, "s"), C(13, "h"), C(12, "d"), C(11, "c"), C(10, "s")]
    revealed = [seat["hole"] for seat in st["seats"]]
    frame = render_table.holdem_frame(st["seats"][0]["hole"], board, 2, revealed=revealed)
    assert len(frame) > 60_000            # this is why the old cap dropped it
    store.write_frame(frame)
    render = _load("render.py")
    payload = {"tool_input": {"command": "python3 scripts/casino.py holdem apply --seat 0 --action call"},
               "tool_response": {"stdout": "{}"}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    render.main()
    out = capsys.readouterr().out
    assert out, "large but legitimate frame must not be dropped"
    assert "▀" in json.loads(out)["systemMessage"]
