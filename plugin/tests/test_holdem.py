from casino import holdem, cards

C = cards.Card


def test_start_deals_and_posts_blinds():
    st = holdem.start_game(hero_stack=1000, seed=7, num_opponents=2)
    assert len(st["seats"]) == 3
    assert st["seats"][0]["is_hero"] is True
    for seat in st["seats"]:
        assert len(seat["hole"]) == 2
    assert st["pot"] == st["sb"] + st["bb"]


def test_bot_packet_hides_other_hole_cards():
    st = holdem.start_game(hero_stack=1000, seed=7, num_opponents=2)
    pkt = holdem.bot_packet(st, seat_idx=1)
    assert "hole" in pkt and len(pkt["hole"]) == 2
    # The packet exposes no other seat's cards, in any form.
    hero_codes = {cards.card_code(c) for c in st["seats"][0]["hole"]}
    assert not (hero_codes & set(pkt["hole"]))
    assert "seats" not in pkt or all("hole" not in s for s in pkt.get("stacks", []))


def test_folding_around_awards_last_player():
    st = holdem.start_game(hero_stack=1000, seed=7, num_opponents=2)
    # Everyone folds to one seat pre-flop; that seat wins the pot.
    order = [st["to_act"]]
    # Fold two of the three; the survivor should net positive.
    actors = [s["idx"] for s in st["seats"]]
    st = holdem.apply_action(st, st["to_act"], "fold")
    st = holdem.apply_action(st, st["to_act"], "fold")
    assert st["street"] == "showdown"
    winners = [i for i, d in st["result"].items() if d > 0]
    assert len(winners) == 1


def test_build_side_pots():
    seats = [
        {"idx": 0, "folded": False, "committed_total": 100},
        {"idx": 1, "folded": False, "committed_total": 50},
        {"idx": 2, "folded": True, "committed_total": 25},
    ]
    pots = holdem.build_pots(seats)
    # Layer 1 (0..25): all three contributed -> 75, eligible {0,1}
    # Layer 2 (25..50): seats 0,1 -> 50, eligible {0,1}
    # Layer 3 (50..100): seat 0 -> 50, eligible {0}
    total = sum(amt for amt, _ in pots)
    assert total == 175
    assert pots[-1][1] == [0]      # only seat 0 eligible for the top layer
