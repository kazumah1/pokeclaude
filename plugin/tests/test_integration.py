import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_cli():
    path = os.path.join(ROOT, "scripts", "casino.py")
    spec = importlib.util.spec_from_file_location("casino_cli", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_balance_reports_starting_stake(casino_home):
    cli = _load_cli()
    out = cli.dispatch(["balance"])
    assert out["bankroll"] == 10000


def test_stakes_toggle_persists(casino_home):
    cli = _load_cli()
    cli.dispatch(["stakes", "real"])
    from casino import store
    assert store.load()["config"]["stakes"] == "real"


def test_blackjack_round_updates_bankroll_and_writes_frame(casino_home):
    cli = _load_cli()
    from casino import store
    deal = cli.dispatch(["bj", "deal", "--bet", "100"])
    # A natural blackjack settles at the deal; otherwise we stand to finish.
    out = deal if deal.get("phase") == "done" or "outcome" in deal else cli.dispatch(["bj", "stand"])
    assert out["outcome"] in {"win", "lose", "push", "dealer_bust", "player_blackjack"}
    assert os.path.exists(store.frame_path())
    # Bankroll moved by the payout (or stayed for a push).
    assert out["bankroll"] == 10000 + out["payout"]


def test_bet_above_bankroll_is_rejected(casino_home):
    cli = _load_cli()
    out = cli.dispatch(["bj", "deal", "--bet", "999999"])
    assert out.get("error")
    from casino import store
    assert store.load()["bankroll"] == 10000     # unchanged


def test_roulette_spin_returns_number(casino_home):
    cli = _load_cli()
    cli.dispatch(["roulette", "bet", "100 on red"])
    out = cli.dispatch(["roulette", "spin"])
    assert 0 <= out["number"] <= 36


def test_holdem_packet_redacts_hero(casino_home):
    cli = _load_cli()
    cli.dispatch(["holdem", "start", "--opponents", "2"])
    out = cli.dispatch(["holdem", "packet", "--seat", "1"])
    assert len(out["packet"]["hole"]) == 2


def test_holdem_survives_multiple_actions(casino_home):
    cli = _load_cli()
    cli.dispatch(["holdem", "start", "--opponents", "2"])
    from casino import store
    first = store.load()["game"]["data"]["to_act"]
    out1 = cli.dispatch(["holdem", "apply", "--seat", str(first), "--action", "fold"])
    assert "error" not in out1
    # A second action must not crash on cards reloaded from disk.
    if out1.get("street") != "showdown":
        out2 = cli.dispatch(["holdem", "apply", "--seat", str(out1["to_act"]), "--action", "fold"])
        assert "error" not in out2


def test_full_holdem_hand_to_showdown(casino_home):
    cli = _load_cli()
    start = cli.dispatch(["holdem", "start", "--opponents", "2"])
    assert "hero_hole" in start
    from casino import store
    guard = 0
    while True:
        game = store.load()["game"]
        if game is None:                       # showdown settled and cleared the game
            break
        data = game["data"]
        if data["street"] == "showdown":        # defensive: settled but not yet cleared
            break
        seat = data["to_act"]
        # Everyone just calls/checks to force the hand to a showdown.
        pkt = cli.dispatch(["holdem", "packet", "--seat", str(seat)])
        action = "check" if "check" in pkt["legal"] else "call"
        res = cli.dispatch(["holdem", "apply", "--seat", str(seat), "--action", action])
        if "result" in res:                     # engine reached showdown and settled the hand
            break
        guard += 1
        assert guard < 50, "hand did not converge"
    assert os.path.exists(store.frame_path())


def test_roulette_bankroll_conserved(casino_home):
    cli = _load_cli()
    cli.dispatch(["roulette", "bet", "100 on red; 50 on 7"])
    out = cli.dispatch(["roulette", "spin"])
    from casino import store
    assert store.load()["bankroll"] == 10000 + out["payout"]


def test_blackjack_double_cannot_overdraw_bankroll(casino_home, monkeypatch):
    cli = _load_cli()
    from casino import store, rng
    # Pin the deal to seed 0 — a non-natural hand where doubling is legal — so the
    # overdraw guard is exercised deterministically on every run (not just the
    # ~90% of deals that aren't a natural blackjack).
    monkeypatch.setattr(rng, "make_seed", lambda: 0)
    deal = cli.dispatch(["bj", "deal", "--bet", "6000"])   # 6000 <= 10000, legal
    assert deal.get("phase") != "done" and "double" in deal.get("legal", [])
    out = cli.dispatch(["bj", "double"])                    # 6000 -> 12000 exposure > 10000
    assert out.get("error")                                 # rejected
    assert store.load()["bankroll"] == 10000                # unchanged
    # Bankroll must never go negative regardless of path.
    assert store.load()["bankroll"] >= 0


def test_real_mode_allows_overdraw_bet(casino_home, monkeypatch):
    cli = _load_cli()
    from casino import store, roulette
    cli.dispatch(["stakes", "real"])
    # 15000 > 10000 bankroll, allowed in real mode
    out = cli.dispatch(["roulette", "bet", "15000 on 7"])
    assert "error" not in out
    # force a loss: spin lands on 8, not 7
    monkeypatch.setattr(roulette, "spin", lambda seed: 8)
    res = cli.dispatch(["roulette", "spin"])
    assert res["payout"] == -15000
    assert res["burn"] == 5000            # shortfall 15000 - 10000, under the 20000 cap
    assert store.load()["bankroll"] == 0  # floored, never negative


def test_sim_mode_still_rejects_overdraw_bet(casino_home):
    cli = _load_cli()
    from casino import store
    # default stakes are sim
    out = cli.dispatch(["roulette", "bet", "15000 on 7"])
    assert out.get("error")
    assert store.load()["bankroll"] == 10000  # unchanged


def test_real_mode_funded_loss_does_not_burn(casino_home, monkeypatch):
    cli = _load_cli()
    from casino import store, roulette
    cli.dispatch(["stakes", "real"])
    cli.dispatch(["roulette", "bet", "100 on 7"])
    monkeypatch.setattr(roulette, "spin", lambda seed: 8)  # lose 100
    res = cli.dispatch(["roulette", "spin"])
    assert res["payout"] == -100
    assert res["burn"] == 0                       # fully shielded by bankroll
    assert store.load()["bankroll"] == 10000 - 100


def test_roulette_straight_up_win_grants_mythical(casino_home, pokeclaude_home, monkeypatch):
    cli = _load_cli()
    from casino import store, roulette
    from pokeclaude import store as dex_store, encounter
    cli.dispatch(["roulette", "bet", "100 on 7"])
    monkeypatch.setattr(roulette, "spin", lambda seed: 7)  # straight-up hit, 35:1
    res = cli.dispatch(["roulette", "spin"])
    assert res["payout"] == 3500
    assert res["granted"] is not None
    assert res["granted"]["tier"] == "MYTHICAL"
    assert res["granted"]["id"] in dex_store.caught_ids(path=dex_store.DEX_PATH)
    # the frame carries the catch line
    with open(store.frame_path()) as f:
        assert "Caught" in f.read()


def test_roulette_loss_grants_nothing(casino_home, pokeclaude_home, monkeypatch):
    cli = _load_cli()
    from casino import roulette
    cli.dispatch(["roulette", "bet", "100 on 7"])
    monkeypatch.setattr(roulette, "spin", lambda seed: 8)  # miss
    res = cli.dispatch(["roulette", "spin"])
    assert res["payout"] == -100
    assert res["granted"] is None


def test_sell_subcommand_round_trips_price_to_bankroll(casino_home, pokeclaude_home):
    cli = _load_cli()
    from casino import store
    from pokeclaude import store as dex_store
    dex_store.record_catch(25, path=dex_store.DEX_PATH)
    dex_store.record_catch(25, path=dex_store.DEX_PATH)  # two Pikachu
    out = cli.dispatch(["sell", "pikachu"])
    assert out["sold"] == {"name": "pikachu", "tier": "COMMON", "price": 500}
    assert out["bankroll"] == 10000 + 500
    assert store.load()["bankroll"] == 10000 + 500


def test_sell_subcommand_last_copy_needs_confirm(casino_home, pokeclaude_home):
    cli = _load_cli()
    from pokeclaude import store as dex_store
    dex_store.record_catch(25, path=dex_store.DEX_PATH)  # one Pikachu
    out = cli.dispatch(["sell", "pikachu"])
    assert out.get("needs_confirm") is True
    out2 = cli.dispatch(["sell", "pikachu", "--confirm"])
    assert out2["sold"]["price"] == 500
    assert 25 not in dex_store.caught_ids(path=dex_store.DEX_PATH)
