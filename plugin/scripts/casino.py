#!/usr/bin/env python3
"""Claude Casino CLI — the seam between Claude and the engines.

Each subcommand mutates persisted state, writes the rendered pixel frame to
disk (which a PostToolUse hook re-emits as a systemMessage), and prints ONE JSON
object to stdout. Claude reads only that JSON to narrate as dealer; it never
generates an outcome. Bankroll/RNG/hand math all live in the engines.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

from casino import (  # noqa: E402
    bankroll, blackjack, cards, holdem, rng, roulette, render_table, store,
)


def _emit(summary):
    print(json.dumps(summary))
    return 0


def _apply_result(payout, is_win, pot_size=0):
    """Move the bankroll by a signed payout and update stats. Returns new state."""
    def mut(s):
        s["bankroll"] = max(0, s["bankroll"] + payout)
        s["stats"]["hands"] += 1
        s["stats"]["net"] += payout
        if is_win:
            s["stats"]["wins"] += 1
        s["stats"]["biggest_pot"] = max(s["stats"]["biggest_pot"], pot_size)
    return store.transaction(mut) or store.load()


# ---- top-level commands -------------------------------------------------

def cmd_balance(args):
    s = store.load()
    return {"bankroll": s["bankroll"], "stats": s["stats"],
            "stakes": s["config"]["stakes"],
            "msg": "Bankroll: %d tokens (%s stakes)."
                   % (s["bankroll"], s["config"]["stakes"])}


def cmd_stakes(args):
    mode = args.mode
    if mode not in ("real", "sim"):
        return {"error": "stakes must be 'real' or 'sim'"}
    store.transaction(lambda s: s["config"].__setitem__("stakes", mode))
    s = store.load()
    note = ("Real stakes ON — losing now burns real tokens (cap %d, or set "
            "CASINO_NO_BURN=1 to disable)." % s["config"]["burn_cap"]
            if mode == "real" else "Stakes are simulated — nothing is burned.")
    return {"bankroll": s["bankroll"], "stakes": mode, "msg": note}


def cmd_reset(args):
    store.transaction(lambda s: s.update({"bankroll": bankroll.START_STAKE,
                                          "game": None}))
    return {"bankroll": bankroll.START_STAKE, "msg": "Bankroll reset to %d."
            % bankroll.START_STAKE}


# ---- blackjack ----------------------------------------------------------

def cmd_bj(args):
    s = store.load()
    if args.bj_cmd == "deal":
        if args.bet <= 0:
            return {"error": "bet must be positive", "bankroll": s["bankroll"]}
        if s["config"]["stakes"] != "real" and args.bet > s["bankroll"]:
            return {"error": "bet exceeds bankroll", "bankroll": s["bankroll"]}
        game = blackjack.new_game(args.bet, rng.make_seed())
        _save_game(game, "blackjack")
        if game["phase"] == "done":       # natural blackjack resolves at the deal
            return _bj_finish(game)
        return _bj_summary(game, s["bankroll"])
    # hit/stand/double operate on the open game
    game = _load_game("blackjack")
    if game is None:
        return {"error": "no blackjack game open", "bankroll": s["bankroll"]}
    if (args.bj_cmd == "double" and s["config"]["stakes"] != "real"
            and 2 * game["bet"] > s["bankroll"]):
        return {"error": "insufficient bankroll to double", "bankroll": s["bankroll"]}
    try:
        game = blackjack.act(game, args.bj_cmd)
    except ValueError as e:
        return {"error": str(e), "bankroll": s["bankroll"]}
    _save_game(game, "blackjack")
    if game["phase"] == "done":
        return _bj_finish(game)
    return _bj_summary(game, s["bankroll"])


def _bj_summary(game, bankroll_now):
    hide = game["phase"] != "done"
    store.write_frame(render_table.blackjack_frame(game["player"], game["dealer"], hide))
    ptot = blackjack.hand_value(game["player"])[0]
    return {"bankroll": bankroll_now, "legal": game["legal"], "player_total": ptot,
            "phase": game["phase"],
            "msg": "You have %d. Options: %s." % (ptot, ", ".join(game["legal"]))}


def _bj_finish(game):
    payout = game["payout"]
    loss = -payout if payout < 0 else 0
    s = store.load()
    _bankroll_after, burn = bankroll.settle_loss(loss, s["bankroll"], s["config"], os.environ)
    state = _apply_result(payout, is_win=payout > 0)
    store.write_frame(render_table.blackjack_frame(game["player"], game["dealer"], False))
    _clear_game()
    return {"bankroll": state["bankroll"], "outcome": game["outcome"],
            "payout": payout, "burn": burn,
            "msg": "%s — net %+d tokens." % (game["outcome"], payout)}


# ---- roulette -----------------------------------------------------------

def cmd_roulette(args):
    s = store.load()
    game = _load_game("roulette") or {"bets": []}
    if args.roulette_cmd == "clear":
        _clear_game()
        return {"bankroll": s["bankroll"], "msg": "Bets cleared."}
    if args.roulette_cmd == "bet":
        parsed = []
        for clause in args.spec.split(";"):
            clause = clause.strip()
            if not clause:
                continue
            try:
                parsed.append(roulette.parse_bet(clause))
            except ValueError as e:
                return {"error": str(e), "bankroll": s["bankroll"]}
        staked = sum(a for _k, _sel, a in parsed) + sum(a for _k, _sel, a in game["bets"])
        if s["config"]["stakes"] != "real" and staked > s["bankroll"]:
            return {"error": "total bets exceed bankroll", "bankroll": s["bankroll"]}
        game["bets"].extend(parsed)
        _save_game(game, "roulette")
        return {"bankroll": s["bankroll"], "bets": len(game["bets"]),
                "msg": "%d bet(s) on the table, %d staked." % (len(game["bets"]), staked)}
    if args.roulette_cmd == "spin":
        if not game["bets"]:
            return {"error": "no bets placed", "bankroll": s["bankroll"]}
        number = roulette.spin(rng.make_seed())
        total_return, net = roulette.resolve(game["bets"], number)
        loss = -net if net < 0 else 0
        _bankroll_after, burn = bankroll.settle_loss(loss, s["bankroll"], s["config"], os.environ)
        state = _apply_result(net, is_win=net > 0)
        store.write_frame(render_table.roulette_frame(number))
        _clear_game()
        return {"bankroll": state["bankroll"], "number": number, "payout": net,
                "burn": burn, "color": _roulette_color(number),
                "msg": "Landed on %d. Net %+d tokens." % (number, net)}


def _roulette_color(n):
    if n == 0:
        return "green"
    return "red" if n in roulette.RED_NUMBERS else "black"


# ---- hold'em ------------------------------------------------------------

def cmd_holdem(args):
    s = store.load()
    if args.holdem_cmd == "start":
        opp = args.opponents
        game = holdem.start_game(s["bankroll"], rng.make_seed(), num_opponents=opp)
        _save_game(game, "holdem")
        _write_holdem_frame(game)
        return {"bankroll": s["bankroll"], "to_act": game["to_act"],
                "pot": game["pot"], "street": game["street"],
                "hero_hole": [cards.card_code(c) for c in game["seats"][0]["hole"]],
                "msg": "Table set with %d opponents. Pot %d. Seat %d to act."
                       % (opp, game["pot"], game["to_act"])}
    game = _load_game("holdem")
    if game is None:
        return {"error": "no hold'em game open", "bankroll": s["bankroll"]}
    game = _rehydrate_holdem(game)
    if args.holdem_cmd == "packet":
        return {"bankroll": s["bankroll"],
                "packet": holdem.bot_packet(game, args.seat),
                "legal": holdem.legal_actions(game),
                "msg": "Decision packet for seat %d (%s)."
                       % (args.seat, game["seats"][args.seat]["name"])}
    if args.holdem_cmd == "apply":
        try:
            game = holdem.apply_action(game, args.seat, args.action, args.amount)
        except ValueError as e:
            return {"error": str(e), "bankroll": s["bankroll"]}
        _save_game(game, "holdem")
        _write_holdem_frame(game)
        if game["street"] == "showdown":
            return _holdem_finish(game)
        return {"bankroll": s["bankroll"], "to_act": game["to_act"],
                "pot": game["pot"], "street": game["street"],
                "board": [cards.card_code(c) for c in game["board"]],
                "legal": holdem.legal_actions(game),
                "msg": "Pot %d. Seat %d to act on the %s."
                       % (game["pot"], game["to_act"], game["street"])}


def _holdem_finish(game):
    hero_delta = game["result"].get(0, 0)
    loss = -hero_delta if hero_delta < 0 else 0
    s = store.load()
    _bankroll_after, burn = bankroll.settle_loss(loss, s["bankroll"], s["config"], os.environ)
    state = _apply_result(hero_delta, is_win=hero_delta > 0, pot_size=game["pot"])
    revealed = [seat["hole"] for seat in game["seats"] if not seat["folded"]]
    store.write_frame(render_table.holdem_frame(
        game["seats"][0]["hole"], game["board"], len(game["seats"]) - 1,
        revealed=revealed))
    _clear_game()
    return {"bankroll": state["bankroll"], "result": game["result"],
            "payout": hero_delta, "burn": burn,
            "board": [cards.card_code(c) for c in game["board"]],
            "msg": "Showdown. You netted %+d tokens." % hero_delta}


def _write_holdem_frame(game):
    store.write_frame(render_table.holdem_frame(
        game["seats"][0]["hole"], game["board"], len(game["seats"]) - 1))


# ---- game state (de)serialization --------------------------------------
# Cards are namedtuples; JSON round-trips them as lists, so rehydrate on load.

def _save_game(game, kind):
    payload = json.loads(json.dumps({"kind": kind, "data": game}))
    store.transaction(lambda s: s.__setitem__("game", payload))


def _load_game(kind):
    g = store.load().get("game")
    if not g or g.get("kind") != kind:
        return None
    return _rehydrate(g["data"], kind)


def _clear_game():
    store.transaction(lambda s: s.__setitem__("game", None))


def _to_card(v):
    return cards.Card(v[0], v[1])


def _rehydrate(data, kind):
    if kind == "blackjack":
        data["deck"] = [_to_card(c) for c in data["deck"]]
        data["player"] = [_to_card(c) for c in data["player"]]
        data["dealer"] = [_to_card(c) for c in data["dealer"]]
    elif kind == "roulette":
        data["bets"] = [tuple(b) for b in data["bets"]]
    elif kind == "holdem":
        data = _rehydrate_holdem(data)
    return data


def _rehydrate_holdem(data):
    seats = data.get("seats") or []
    # Already hydrated if hole cards are Card objects (not JSON lists).
    if seats and seats[0]["hole"] and isinstance(seats[0]["hole"][0], cards.Card):
        return data
    data["deck"] = [_to_card(c) for c in data["deck"]]
    data["board"] = [_to_card(c) for c in data["board"]]
    for seat in seats:
        seat["hole"] = [_to_card(c) for c in seat["hole"]]
    if data.get("result"):
        data["result"] = {int(k): v for k, v in data["result"].items()}
    return data


# ---- arg parsing --------------------------------------------------------

def _build_parser():
    p = argparse.ArgumentParser(prog="casino")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("balance")
    sp = sub.add_parser("stakes"); sp.add_argument("mode")
    sub.add_parser("reset")

    bj = sub.add_parser("bj"); bjs = bj.add_subparsers(dest="bj_cmd", required=True)
    d = bjs.add_parser("deal"); d.add_argument("--bet", type=int, required=True)
    bjs.add_parser("hit"); bjs.add_parser("stand"); bjs.add_parser("double")

    ro = sub.add_parser("roulette"); ros = ro.add_subparsers(dest="roulette_cmd", required=True)
    rb = ros.add_parser("bet"); rb.add_argument("spec")
    ros.add_parser("spin"); ros.add_parser("clear")

    ho = sub.add_parser("holdem"); hos = ho.add_subparsers(dest="holdem_cmd", required=True)
    hs = hos.add_parser("start"); hs.add_argument("--opponents", type=int, default=2)
    hp = hos.add_parser("packet"); hp.add_argument("--seat", type=int, required=True)
    ha = hos.add_parser("apply")
    ha.add_argument("--seat", type=int, required=True)
    ha.add_argument("--action", required=True)
    ha.add_argument("--amount", type=int, default=0)
    return p


_HANDLERS = {
    "balance": cmd_balance, "stakes": cmd_stakes, "reset": cmd_reset,
    "bj": cmd_bj, "roulette": cmd_roulette, "holdem": cmd_holdem,
}


def dispatch(argv):
    args = _build_parser().parse_args(argv)
    return _HANDLERS[args.cmd](args)


def main(argv):
    try:
        return _emit(dispatch(argv))
    except SystemExit:
        raise
    except Exception as e:  # never crash without a JSON reply Claude can read
        return _emit({"error": "internal: %s" % e})


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
