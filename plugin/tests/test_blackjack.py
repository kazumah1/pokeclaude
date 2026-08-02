from casino import blackjack, cards

C = cards.Card


def test_hand_value_soft_and_hard():
    assert blackjack.hand_value([C(14, "s"), C(6, "d")]) == (17, True)   # soft 17
    assert blackjack.hand_value([C(14, "s"), C(6, "d"), C(10, "c")]) == (17, False)  # ace drops to 1
    assert blackjack.hand_value([C(13, "s"), C(13, "d")]) == (20, False)


def test_new_game_deals_two_each_and_sets_legal():
    st = blackjack.new_game(bet=100, seed=1)
    assert len(st["player"]) == 2 and len(st["dealer"]) == 2
    # Non-blackjack hands can hit/stand/double.
    assert "hit" in st["legal"] and "stand" in st["legal"]


def test_player_bust_loses_bet():
    # Force a deterministic bust by driving the state directly.
    st = blackjack.new_game(bet=100, seed=1)
    st["player"] = [C(10, "s"), C(9, "d")]           # 19
    st["deck"] = [C(10, "c")] + st["deck"]           # next hit busts to 29
    st = blackjack.act(st, "hit")
    assert st["phase"] == "done"
    assert st["outcome"] == "bust"
    assert st["payout"] == -100


def test_dealer_stands_on_17():
    st = blackjack.new_game(bet=100, seed=1)
    st["player"] = [C(10, "s"), C(9, "d")]           # 19, stand
    st["dealer"] = [C(10, "h"), C(7, "c")]           # 17 -> must stand
    st = blackjack.act(st, "stand")
    assert st["outcome"] == "win"                    # 19 beats 17
    assert st["payout"] == 100


def test_natural_blackjack_pays_three_to_two():
    st = blackjack.new_game(bet=100, seed=1)
    st["player"] = [C(14, "s"), C(13, "d")]          # natural 21
    st["dealer"] = [C(10, "h"), C(9, "c")]           # 19, not blackjack
    st = blackjack._settle_if_natural(st)
    assert st["outcome"] == "player_blackjack"
    assert st["payout"] == 150
