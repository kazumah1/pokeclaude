"""Compose full game scenes from cards and shapes, returning ANSI strings.

Frames are purely visual — cards, the roulette pocket, opponent card-backs.
Numeric state (totals, pot, stacks, bankroll) is narrated by Claude from the
engine's JSON summary, so the art stays readable and the render layer never
has to draw fonts for arbitrary numbers.
"""
from casino import cards, frame, render_cards

FELT = (16, 92, 60)

# European roulette pocket colors. 0 is green.
_RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

# Roulette numerals need digits 0 and 1, which the card-rank FONT lacks.
_EXTRA_DIGITS = {
    "0": ["111", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "111"],
}


def _digit_glyph(d):
    return _EXTRA_DIGITS[d] if d in _EXTRA_DIGITS else render_cards.FONT[d]


def _row_of_cards(card_list, faceups=None):
    if not card_list:
        return frame.blank(render_cards.CARD_W, render_cards.CARD_H, None)
    grids = []
    for i, c in enumerate(card_list):
        fu = True if faceups is None else faceups[i]
        grids.append(render_cards.render_card(c, faceup=fu))
    return frame.hconcat(grids, gap=2, bg=None)


def blackjack_frame(player, dealer, hide_hole=True):
    dealer_faceups = [True] + [not hide_hole] + [True] * (len(dealer) - 2)
    dealer_faceups = dealer_faceups[: len(dealer)]
    top = _row_of_cards(dealer, faceups=dealer_faceups)
    bottom = _row_of_cards(player)
    grid = frame.vconcat([top, bottom], gap=2, bg=None)
    return frame.render(grid, bg=FELT)


def _pocket_color(number):
    if number == 0:
        return (16, 140, 80)
    return (200, 40, 50) if number in _RED_NUMBERS else (28, 28, 34)


def roulette_frame(number):
    # Draw the winning number as scaled glyphs on its pocket color.
    digits = str(number)
    glyph_grids = []
    for d in digits:
        g = frame.blank(3, 5, None)
        frame.stamp(g, _digit_glyph(d), 0, 0, (244, 244, 238))
        glyph_grids.append(frame.scale(g, 3))
    numeral = frame.hconcat(glyph_grids, gap=3, bg=None)
    # Frame the numeral in a padded pocket-colored panel.
    pad = 4
    w = frame._width(numeral) + pad * 2
    h = len(numeral) + pad * 2
    panel = frame.blank(w, h, _pocket_color(number))
    for j in range(len(numeral)):
        for i in range(len(numeral[j])):
            if numeral[j][i] is not None:
                panel[j + pad][i + pad] = numeral[j][i]
    return frame.render(panel, bg=FELT)


def holdem_frame(hero_hole, board, opponents, revealed=None):
    rows = []
    # Opponents: revealed hole cards at showdown, else pairs of backs.
    if revealed:
        opp_rows = [_row_of_cards(h) for h in revealed]
        rows.append(frame.hconcat(opp_rows, gap=4, bg=None))
    else:
        backs = [render_cards.card_back() for _ in range(opponents * 2)]
        rows.append(frame.hconcat(backs, gap=2, bg=None) if backs
                    else frame.blank(1, 1, None))
    # Community board (face up).
    if board:
        rows.append(_row_of_cards(board))
    # Hero hole cards (always face up — only ever rendered to the hero's own terminal).
    rows.append(_row_of_cards(hero_hole))
    grid = frame.vconcat(rows, gap=2, bg=None)
    return frame.render(grid, bg=FELT)
