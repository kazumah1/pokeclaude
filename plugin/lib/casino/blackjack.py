"""Blackjack vs. the dealer. Single hand (no split/insurance in v1).

Dealer stands on 17 (including soft 17), blackjack pays 3:2. The engine owns the
shoe and every draw; payout is the signed net token change vs. the bankroll.
"""
from casino import cards, rng


def hand_value(cards_list):
    """(best_total, is_soft). Aces are 11 until that would bust, then 1."""
    total = sum(min(c.rank, 10) if c.rank < 14 else 11 for c in cards_list)
    aces = sum(1 for c in cards_list if c.rank == 14)
    soft = aces > 0
    while total > 21 and aces:
        total -= 10       # demote an ace from 11 to 1
        aces -= 1
        soft = aces > 0
    return total, soft


def _is_blackjack(hand):
    return len(hand) == 2 and hand_value(hand)[0] == 21


def new_game(bet, seed):
    deck = rng.shuffle(cards.make_deck(), seed)
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    state = {
        "bet": bet,
        "seed": seed,
        "deck": deck,
        "player": player,
        "dealer": dealer,
        "phase": "player",
        "outcome": None,
        "payout": 0,
        "legal": [],
    }
    return _settle_if_natural(state)


def _settle_if_natural(state):
    player_bj = _is_blackjack(state["player"])
    dealer_bj = _is_blackjack(state["dealer"])
    if player_bj or dealer_bj:
        state["phase"] = "done"
        if player_bj and dealer_bj:
            state["outcome"] = "push"
            state["payout"] = 0
        elif player_bj:
            state["outcome"] = "player_blackjack"
            state["payout"] = int(state["bet"] * 3 // 2)   # 3:2
        else:
            state["outcome"] = "lose"
            state["payout"] = -state["bet"]
        state["legal"] = []
    else:
        state["legal"] = ["hit", "stand", "double"]
    return state


def _resolve_dealer(state):
    dealer = state["dealer"]
    while True:
        total, _soft = hand_value(dealer)
        if total >= 17:
            break
        dealer.append(state["deck"].pop())
    return hand_value(dealer)[0]


def _finish(state):
    player_total = hand_value(state["player"])[0]
    dealer_total = _resolve_dealer(state)
    state["phase"] = "done"
    state["legal"] = []
    if dealer_total > 21:
        state["outcome"] = "dealer_bust"
        state["payout"] = state["bet"]
    elif player_total > dealer_total:
        state["outcome"] = "win"
        state["payout"] = state["bet"]
    elif player_total < dealer_total:
        state["outcome"] = "lose"
        state["payout"] = -state["bet"]
    else:
        state["outcome"] = "push"
        state["payout"] = 0
    return state


def act(state, action):
    if state["phase"] != "player":
        raise ValueError("no player action available")
    if action not in state["legal"]:
        raise ValueError("illegal action: %s" % action)

    if action == "hit":
        state["player"].append(state["deck"].pop())
        total, _ = hand_value(state["player"])
        if total > 21:
            state["phase"] = "done"
            state["outcome"] = "bust"
            state["payout"] = -state["bet"]
            state["legal"] = []
        else:
            # After the first hit, doubling is no longer offered.
            state["legal"] = ["hit", "stand"]
        return state

    if action == "stand":
        return _finish(state)

    if action == "double":
        state["bet"] *= 2
        state["player"].append(state["deck"].pop())
        total, _ = hand_value(state["player"])
        if total > 21:
            state["phase"] = "done"
            state["outcome"] = "bust"
            state["payout"] = -state["bet"]
            state["legal"] = []
            return state
        return _finish(state)

    raise ValueError("unknown action: %s" % action)
