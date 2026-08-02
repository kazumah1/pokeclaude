"""No-limit Texas Hold'em. The engine owns all hole cards; Claude drives the
bots via isolated subagents that receive only bot_packet() — a seat's own cards
plus public state. No single context ever holds both the hero's hole cards and a
betting decision, which is what makes Claude-driven poker fair.
"""
from casino import cards, rng

PERSONAS = [
    {"name": "Rocky", "style": "tight-passive", "blurb": "folds junk, only bets the nuts"},
    {"name": "Blaze", "style": "loose-aggressive", "blurb": "raises relentlessly, bluffs a lot"},
    {"name": "Calvin", "style": "calling-station", "blurb": "calls too much, rarely folds"},
    {"name": "Vera", "style": "balanced", "blurb": "solid, hard to read"},
    {"name": "Dice", "style": "maniac", "blurb": "chaos; huge bets, wild bluffs"},
]


def _draw_personas(seed, n):
    import random
    pool = list(PERSONAS)
    random.Random(seed ^ 0x9E3779B9).shuffle(pool)
    return pool[:n]


def start_game(hero_stack, seed, num_opponents=2, sb=25, bb=50):
    deck = rng.shuffle(cards.make_deck(), seed)
    personas = _draw_personas(seed, num_opponents)
    seats = [{
        "idx": 0, "name": "You", "persona": None, "stack": hero_stack,
        "hole": [], "folded": False, "allin": False,
        "committed_round": 0, "committed_total": 0, "is_hero": True, "acted": False,
    }]
    for i, p in enumerate(personas, start=1):
        seats.append({
            "idx": i, "name": p["name"], "persona": p, "stack": hero_stack,
            "hole": [], "folded": False, "allin": False,
            "committed_round": 0, "committed_total": 0, "is_hero": False, "acted": False,
        })
    # Deal two hole cards to each seat.
    for _ in range(2):
        for seat in seats:
            seat["hole"].append(deck.pop())

    state = {
        "seed": seed, "deck": deck, "seats": seats, "board": [],
        "pot": 0, "street": "preflop", "current_bet": 0, "min_raise": bb,
        "button": 0, "sb": sb, "bb": bb, "result": None,
    }
    n = len(seats)
    sb_idx = (state["button"] + 1) % n
    bb_idx = (state["button"] + 2) % n
    _post(state, sb_idx, sb)
    _post(state, bb_idx, bb)
    state["current_bet"] = bb
    state["min_raise"] = bb
    state["to_act"] = (bb_idx + 1) % n
    return state


def _post(state, idx, amount):
    seat = state["seats"][idx]
    amount = min(amount, seat["stack"])
    seat["stack"] -= amount
    seat["committed_round"] += amount
    seat["committed_total"] += amount
    state["pot"] += amount
    if seat["stack"] == 0:
        seat["allin"] = True


def _contenders(state):
    return [s for s in state["seats"] if not s["folded"]]


def _actionable(state):
    return [s for s in state["seats"] if not s["folded"] and not s["allin"]]


def legal_actions(state):
    seat = state["seats"][state["to_act"]]
    to_call = state["current_bet"] - seat["committed_round"]
    actions = ["fold"]
    if to_call == 0:
        actions.append("check")
    else:
        actions.append("call")
    if seat["stack"] > to_call:
        actions.append("raise")
    return actions


def bot_packet(state, seat_idx):
    seat = state["seats"][seat_idx]
    to_call = state["current_bet"] - seat["committed_round"]
    return {
        "seat": seat_idx,
        "name": seat["name"],
        "persona": seat["persona"],
        "hole": [cards.card_code(c) for c in seat["hole"]],
        "board": [cards.card_code(c) for c in state["board"]],
        "pot": state["pot"],
        "to_call": to_call,
        "min_raise": state["min_raise"],
        "stacks": [{"seat": s["idx"], "name": s["name"], "stack": s["stack"],
                    "folded": s["folded"]} for s in state["seats"]],
        "position": "button" if seat_idx == state["button"] else "other",
        "street": state["street"],
    }


def _next_to_act(state, start):
    n = len(state["seats"])
    i = (start + 1) % n
    for _ in range(n):
        seat = state["seats"][i]
        if not seat["folded"] and not seat["allin"]:
            return i
        i = (i + 1) % n
    return None


def _round_closed(state):
    live = _actionable(state)
    if not live:
        return True
    return all(s["acted"] and s["committed_round"] == state["current_bet"] for s in live)


def _reset_round(state):
    for seat in state["seats"]:
        seat["committed_round"] = 0
        seat["acted"] = False
    state["current_bet"] = 0
    state["min_raise"] = state["bb"]


def _advance_street(state):
    order = ["preflop", "flop", "turn", "river", "showdown"]
    nxt = order[order.index(state["street"]) + 1]
    state["street"] = nxt
    if nxt == "flop":
        state["board"].extend([state["deck"].pop() for _ in range(3)])
    elif nxt in ("turn", "river"):
        state["board"].append(state["deck"].pop())
    if nxt == "showdown":
        return showdown(state)
    _reset_round(state)
    # First to act post-flop is left of the button among live seats.
    state["to_act"] = _next_to_act(state, state["button"])
    if state["to_act"] is None or len(_actionable(state)) == 0:
        # Everyone all-in: run out remaining streets to showdown.
        return _advance_street(state)
    return state


def apply_action(state, seat_idx, action, amount=0):
    if state["street"] == "showdown":
        raise ValueError("hand is over")
    if seat_idx != state["to_act"]:
        raise ValueError("not seat %d's turn" % seat_idx)
    if action not in legal_actions(state):
        raise ValueError("illegal action: %s" % action)

    seat = state["seats"][seat_idx]
    to_call = state["current_bet"] - seat["committed_round"]

    if action == "fold":
        seat["folded"] = True
    elif action == "check":
        pass
    elif action == "call":
        pay = min(to_call, seat["stack"])
        _post(state, seat_idx, pay)
    elif action == "raise":
        # `amount` is the total this seat's bet becomes for the round.
        target = max(amount, state["current_bet"] + state["min_raise"])
        pay = min(target - seat["committed_round"], seat["stack"])
        raise_size = (seat["committed_round"] + pay) - state["current_bet"]
        _post(state, seat_idx, pay)
        if raise_size > 0:
            state["current_bet"] = seat["committed_round"]
            state["min_raise"] = max(state["min_raise"], raise_size)
            # A raise reopens the action for everyone else.
            for other in state["seats"]:
                if other is not seat and not other["folded"] and not other["allin"]:
                    other["acted"] = False
    seat["acted"] = True

    # Only one contender left -> hand ends now, that seat wins the pot.
    if len(_contenders(state)) == 1:
        return _award_uncontested(state)

    if _round_closed(state):
        return _advance_street(state)

    nxt = _next_to_act(state, seat_idx)
    if nxt is None:
        return _advance_street(state)
    state["to_act"] = nxt
    return state


def _award_uncontested(state):
    winner = _contenders(state)[0]
    result = {s["idx"]: -s["committed_total"] for s in state["seats"]}
    result[winner["idx"]] = state["pot"] - winner["committed_total"]
    winner["stack"] += state["pot"]
    state["street"] = "showdown"
    state["result"] = result
    return state


def build_pots(seats):
    """Layered side pots. Returns [(amount, [eligible_idx, ...]), ...]."""
    levels = sorted({s["committed_total"] for s in seats if s["committed_total"] > 0})
    pots = []
    prev = 0
    for lvl in levels:
        amount = 0
        for s in seats:
            amount += min(s["committed_total"], lvl) - min(s["committed_total"], prev)
        eligible = [s["idx"] for s in seats
                    if not s["folded"] and s["committed_total"] >= lvl]
        pots.append((amount, eligible))
        prev = lvl
    return pots


def showdown(state):
    seats = state["seats"]
    result = {s["idx"]: -s["committed_total"] for s in seats}
    for amount, eligible in build_pots(seats):
        if not eligible:
            continue
        scored = [(cards.evaluate(seats[i]["hole"] + state["board"]), i)
                  for i in eligible]
        best = max(score for score, _ in scored)
        winners = [i for score, i in scored if score == best]
        share = amount // len(winners)
        remainder = amount - share * len(winners)
        for w in winners:
            seats[w]["stack"] += share
            result[w] += share
        if remainder:
            # Odd chip to the first winner in seat order.
            seats[winners[0]]["stack"] += remainder
            result[winners[0]] += remainder
    state["street"] = "showdown"
    state["result"] = result
    return state
