def test_package_imports():
    import casino  # noqa: F401


from casino import cards


def test_make_deck_is_52_unique():
    deck = cards.make_deck()
    assert len(deck) == 52
    assert len(set(deck)) == 52


def test_rank_labels_and_glyphs():
    assert cards.rank_label(14) == "A"
    assert cards.rank_label(10) == "10"
    assert cards.rank_glyph(10) == "T"
    assert cards.rank_glyph(13) == "K"


def test_card_code():
    assert cards.card_code(cards.Card(14, "s")) == "As"
    assert cards.card_code(cards.Card(10, "d")) == "Td"
    assert cards.card_code(cards.Card(2, "c")) == "2c"


def _hand(codes):
    # codes like "As Ks Qs Js Ts"
    lut = {"T": 10, "J": 11, "Q": 12, "K": 13, "A": 14}
    out = []
    for c in codes.split():
        r = c[:-1]
        out.append(cards.Card(lut.get(r, None) or int(r), c[-1]))
    return out


def test_royal_flush_beats_quads():
    royal = cards.evaluate(_hand("As Ks Qs Js Ts 2d 3c"))
    quads = cards.evaluate(_hand("Ah Ad Ac As Kd 2c 3h"))
    assert royal[0] == 8
    assert quads[0] == 7
    assert royal > quads


def test_wheel_straight_is_five_high():
    score = cards.evaluate(_hand("Ah 2d 3c 4s 5h 9d Kc"))
    assert score[0] == 4      # straight
    assert score[1] == 5      # five-high, ace plays low


def test_full_house_tiebreak_by_trips():
    higher = cards.evaluate(_hand("Kh Kd Ks 2c 2d 7h 9s"))
    lower = cards.evaluate(_hand("Qh Qd Qs 9c 9d 7h 2s"))
    assert higher[0] == lower[0] == 6
    assert higher > lower


def test_kicker_breaks_pair_tie():
    a = cards.evaluate(_hand("Ah Ad Kc 9d 4s 3h 2c"))
    b = cards.evaluate(_hand("Ah Ad Qc 9d 4s 3h 2c"))
    assert a[0] == b[0] == 1
    assert a > b


def test_hand_name():
    assert cards.hand_name(cards.evaluate(_hand("As Ks Qs Js Ts"))) == "Straight Flush"
