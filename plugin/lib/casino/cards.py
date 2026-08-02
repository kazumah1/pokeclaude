"""Card model and a pure 5-of-7 poker hand evaluator.

A Card is (rank, suit): rank is an int 2..14 with 14 == Ace, suit is one of
"c" (clubs), "d" (diamonds), "h" (hearts), "s" (spades). Ints make evaluation
and comparison trivial; labels/glyphs are derived only for display.
"""
from collections import namedtuple

Card = namedtuple("Card", ["rank", "suit"])

SUITS = ("c", "d", "h", "s")

_LABELS = {11: "J", 12: "Q", 13: "K", 14: "A"}


def rank_label(rank):
    """Human label: '2'..'9', '10', 'J', 'Q', 'K', 'A'."""
    if rank == 10:
        return "10"
    return _LABELS.get(rank, str(rank))


def rank_glyph(rank):
    """Single-character glyph for the pixel font ('10' collapses to 'T')."""
    label = rank_label(rank)
    return "T" if label == "10" else label


def make_deck():
    """A fresh, ordered 52-card deck."""
    return [Card(rank, suit) for suit in SUITS for rank in range(2, 15)]


def card_code(card):
    """Compact 2-char code, e.g. Card(14,'s') -> 'As', Card(10,'d') -> 'Td'."""
    return "%s%s" % (rank_glyph(card.rank), card.suit)


from collections import Counter
from itertools import combinations

CATEGORY_NAMES = {
    8: "Straight Flush",
    7: "Four of a Kind",
    6: "Full House",
    5: "Flush",
    4: "Straight",
    3: "Three of a Kind",
    2: "Two Pair",
    1: "Pair",
    0: "High Card",
}


def _score_five(five):
    """Score exactly five cards. Returns (category, *tiebreakers)."""
    ranks = sorted((c.rank for c in five), reverse=True)
    suits = [c.suit for c in five]
    counts = Counter(ranks)
    # Sort rank groups by (count, rank) descending: this yields correct
    # tiebreak order for pairs/trips/quads/full houses in one pass.
    ordered = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    pattern = [cnt for _rank, cnt in ordered]
    tiebreak = tuple(rank for rank, _cnt in ordered)

    is_flush = len(set(suits)) == 1

    unique_desc = sorted(set(ranks), reverse=True)
    straight_high = None
    if len(unique_desc) == 5:
        if unique_desc[0] - unique_desc[4] == 4:
            straight_high = unique_desc[0]
        elif unique_desc == [14, 5, 4, 3, 2]:  # ace-low "wheel"
            straight_high = 5

    if is_flush and straight_high is not None:
        return (8, straight_high)
    if pattern == [4, 1]:
        return (7,) + tiebreak
    if pattern == [3, 2]:
        return (6,) + tiebreak
    if is_flush:
        return (5,) + tuple(ranks)
    if straight_high is not None:
        return (4, straight_high)
    if pattern == [3, 1, 1]:
        return (3,) + tiebreak
    if pattern == [2, 2, 1]:
        return (2,) + tiebreak
    if pattern == [2, 1, 1, 1]:
        return (1,) + tiebreak
    return (0,) + tuple(ranks)


def evaluate(hand):
    """Best 5-card score from 5, 6, or 7 cards. Higher tuple == stronger."""
    if len(hand) < 5:
        raise ValueError("need at least 5 cards to evaluate")
    return max(_score_five(list(combo)) for combo in combinations(hand, 5))


def hand_name(score):
    return CATEGORY_NAMES[score[0]]
