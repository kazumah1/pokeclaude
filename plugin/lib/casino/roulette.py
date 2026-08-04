"""European single-zero roulette (pockets 0..36).

resolve() takes parsed bets and the winning number and returns the total amount
returned (stake + profit on wins) and the net profit/loss. spin() draws the
winning pocket from a seed so results are reproducible.
"""
from casino import rng

RED_NUMBERS = frozenset(
    {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
)

_MULT = {
    "straight": 35,
    "split": 17,
    "street": 11,
    "corner": 8,
    "line": 5,
    "dozen": 2,
    "column": 2,
    "color": 1,
    "parity": 1,
    "half": 1,
}


def payout_multiplier(kind):
    return _MULT[kind]


def parse_bet(text):
    """Parse one clause: '<amount> on <target>'. Returns (kind, selection, amount)."""
    parts = text.lower().replace(" on ", " ").split()
    if len(parts) < 2:
        raise ValueError("cannot parse bet: %r" % text)
    try:
        amount = int(parts[0])
    except ValueError:
        raise ValueError("bet must start with an amount: %r" % text)
    if amount <= 0:
        raise ValueError("bet amount must be positive: %r" % text)
    target = parts[1:]
    word = target[0]

    if word in ("red", "black"):
        return ("color", word, amount)
    if word in ("odd", "even"):
        return ("parity", word, amount)
    if word in ("high", "low"):
        return ("half", word, amount)
    if word in ("dozen", "column"):
        if len(target) < 2 or not target[1].isdigit():
            raise ValueError("%s bet needs a number 1-3: %r" % (word, text))
        n = int(target[1])
        if n not in (1, 2, 3):
            raise ValueError("%s must be 1, 2, or 3: %r" % (word, text))
        return (word, n, amount)
    if word.isdigit():
        n = int(word)
        if 0 <= n <= 36:
            return ("straight", n, amount)
    raise ValueError("unknown bet target: %r" % text)


def _wins(kind, selection, number):
    if number == 0:
        # Zero loses all outside bets; only a straight-up on 0 wins.
        return kind == "straight" and selection == 0
    if kind == "straight":
        return number == selection
    if kind == "color":
        is_red = number in RED_NUMBERS
        return (selection == "red") == is_red
    if kind == "parity":
        return (number % 2 == 1) == (selection == "odd")
    if kind == "half":
        return (number >= 19) == (selection == "high")
    if kind == "dozen":
        return (number - 1) // 12 + 1 == selection
    if kind == "column":
        return (number - 1) % 3 + 1 == selection
    return False


def resolve(bets, number):
    total_return = 0
    staked = 0
    for kind, selection, amount in bets:
        staked += amount
        if _wins(kind, selection, number):
            total_return += amount + amount * payout_multiplier(kind)
    return total_return, total_return - staked


def spin(seed):
    return rng.randint(0, 36, seed)
