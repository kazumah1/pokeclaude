from casino import render_cards, cards


def test_card_dimensions():
    g = render_cards.render_card(cards.Card(14, "s"))
    assert len(g) == render_cards.CARD_H
    assert len(g[0]) == render_cards.CARD_W


def test_facedown_matches_back():
    assert render_cards.render_card(cards.Card(2, "c"), faceup=False) == render_cards.card_back()


def test_red_suit_uses_red_pixels():
    g = render_cards.render_card(cards.Card(14, "h"))
    flat = [px for row in g for px in row if px is not None]
    assert render_cards.RED in flat


def test_every_card_renders():
    for card in cards.make_deck():
        g = render_cards.render_card(card)
        assert any(px is not None for row in g for px in row)


from casino import render_table


def test_blackjack_frame_hides_hole_card():
    player = [cards.Card(14, "s"), cards.Card(13, "h")]
    dealer = [cards.Card(10, "d"), cards.Card(9, "c")]
    hidden = render_table.blackjack_frame(player, dealer, hide_hole=True)
    shown = render_table.blackjack_frame(player, dealer, hide_hole=False)
    assert "▀" in hidden
    assert hidden != shown       # the hole card changes the picture


def test_roulette_frame_all_numbers_render():
    for n in range(0, 37):
        out = render_table.roulette_frame(n)
        assert "▀" in out


def test_holdem_frame_renders():
    hero = [cards.Card(14, "s"), cards.Card(14, "h")]
    board = [cards.Card(2, "c"), cards.Card(7, "d"), cards.Card(11, "s")]
    out = render_table.holdem_frame(hero, board, opponents=2)
    assert "▀" in out
