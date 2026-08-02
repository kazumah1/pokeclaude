"""Procedural pixel-art playing cards.

Every one of the 52 cards is drawn from parts — a rounded white card body with a
gray border, a 3x5 rank glyph in the corners, and a 7x7 suit pip in the center —
tinted red for hearts/diamonds and near-black for spades/clubs. No per-card art
is stored; a card is (glyph + pip + suit color).
"""
from casino import cards, frame

CARD_W = 16
CARD_H = 24

WHITE = (244, 244, 238)
GRAY = (70, 72, 84)
RED = (200, 40, 50)
BLACK = (28, 28, 34)
BACK_DARK = (34, 68, 150)
BACK_LIGHT = (74, 116, 205)

# 3x5 rank glyphs.
FONT = {
    "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"],
    "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"],
    "7": ["111", "001", "010", "010", "010"],
    "8": ["111", "101", "111", "101", "111"],
    "9": ["111", "101", "111", "001", "111"],
    "T": ["111", "010", "010", "010", "111"],
    "J": ["001", "001", "001", "101", "111"],
    "Q": ["111", "101", "101", "111", "011"],
    "K": ["101", "101", "110", "101", "101"],
    "A": ["111", "101", "111", "101", "101"],
}

# 7x7 suit pips.
PIPS = {
    "h": ["0110110", "1111111", "1111111", "1111111", "0111110", "0011100", "0001000"],
    "d": ["0001000", "0011100", "0111110", "1111111", "0111110", "0011100", "0001000"],
    "s": ["0001000", "0011100", "0111110", "1111111", "1111111", "0101010", "0011100"],
    "c": ["0011100", "0011100", "1101011", "1111111", "1101011", "0001000", "0011100"],
}


def _suit_color(suit):
    return RED if suit in ("h", "d") else BLACK


def _is_corner(x, y):
    """The single extreme corner pixel on each side, for a rounded look."""
    return x in (0, CARD_W - 1) and y in (0, CARD_H - 1)


def _card_body(fill_interior):
    grid = frame.blank(CARD_W, CARD_H, None)
    for y in range(CARD_H):
        for x in range(CARD_W):
            if _is_corner(x, y):
                continue
            on_border = x <= 1 or x >= CARD_W - 2 or y <= 1 or y >= CARD_H - 2
            grid[y][x] = GRAY if on_border else fill_interior(x, y)
    return grid


def render_card(card, faceup=True):
    if not faceup:
        return card_back()
    grid = _card_body(lambda x, y: WHITE)
    color = _suit_color(card.suit)
    glyph = FONT[cards.rank_glyph(card.rank)]
    pip = PIPS[card.suit]
    frame.stamp(grid, glyph, 3, 3, color)                      # top-left rank
    frame.stamp(grid, pip, CARD_W // 2 - 3, CARD_H // 2 - 3, color)  # center pip
    frame.stamp(grid, glyph, CARD_W - 6, CARD_H - 8, color)    # bottom-right rank
    return grid


def card_back():
    def checker(x, y):
        return BACK_LIGHT if (x + y) % 2 == 0 else BACK_DARK
    return _card_body(checker)
