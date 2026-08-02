"""Seeded randomness. Every game records its seed so any hand is reproducible
and tamper-evident: given the seed, the exact shuffle can be replayed."""
import random
import secrets


def make_seed():
    """A fresh 63-bit seed for a new game."""
    return secrets.randbits(63)


def shuffle(items, seed):
    """A deterministic shuffled *copy* of items. Same seed -> same order."""
    out = list(items)
    random.Random(seed).shuffle(out)
    return out


def randint(low, high, seed):
    """A deterministic integer in [low, high] from seed. Same seed -> same draw."""
    return random.Random(seed).randint(low, high)
