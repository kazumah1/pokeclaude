"""Catch-rate model and species selection.

Rate is calibrated against measured throughput rather than guessed. Measured
across 157 real sessions, deduplicating transcript records by message id (see
the note below -- this matters a lot), the median assistant output rate is
~1,100 tokens/min. A target of roughly one catch per 45-60 minutes of active
work therefore means one catch per ~50k-65k output tokens. TOKENS_PER_CATCH
encodes that directly, so the knob stays interpretable: raise it for rarer
catches, lower it for more.

An earlier calibration used ~3,300 tok/min, which was 3x too high because the
same message was counted once per content block. Both the measurement and the
hook's reader had to be fixed; with per-record summing AND the inflated
baseline, the two errors partly cancelled, which is exactly why the bug survived
a first round of testing. If this constant is ever retuned, measure with
deduplication.

Odds are derived per-turn from real `output_tokens` in the transcript, so a long
grinding turn genuinely improves your chances and an idle one does not.

Duplicates are possible but deliberately rarer than new species: a duplicate
roll is kept at DUPLICATE_WEIGHT of a new one, so the dex keeps filling in while
still handing out the occasional repeat. As the dex nears completion the
remaining-new pool shrinks, so duplicates naturally dominate the tail instead of
catches drying up entirely.
"""
import hashlib
import os
import random

# One catch per this many assistant output tokens (see module docstring).
# 58k / ~1,100 tok/min ~= 53 min per catch, inside the 45-60 min target.
TOKENS_PER_CATCH = 58_000

# A duplicate species is this much as likely as an unseen one.
DUPLICATE_WEIGHT = 0.25

# Never let a single enormous turn become a guaranteed catch; keeps the
# surprise intact and stops one 500k-token workflow from minting several.
MAX_TURN_PROBABILITY = 0.5

# Legendaries/mythicals are rarer. Everything unlisted has weight 1.0.
RARITY = {
    144: 0.12, 145: 0.12, 146: 0.12, 150: 0.06, 151: 0.04,  # gen 1
    243: 0.12, 244: 0.12, 245: 0.12, 249: 0.06, 250: 0.06, 251: 0.04,  # gen 2
    377: 0.12, 378: 0.12, 379: 0.12, 380: 0.10, 381: 0.10,  # gen 3
    382: 0.06, 383: 0.06, 384: 0.05, 385: 0.04, 386: 0.04,
}


def turn_probability(output_tokens, tokens_per_catch=TOKENS_PER_CATCH):
    """Chance that a turn of `output_tokens` yields a catch."""
    if output_tokens <= 0:
        return 0.0
    return min(MAX_TURN_PROBABILITY, float(output_tokens) / float(tokens_per_catch))


def _rng(seed=None):
    """Seedable RNG. Unseeded draws use os.urandom so parallel sessions that
    start in the same second cannot roll identically."""
    if seed is not None:
        return random.Random(seed)
    return random.Random(int.from_bytes(os.urandom(8), "big"))


def roll(output_tokens, seed=None, tokens_per_catch=TOKENS_PER_CATCH):
    p = turn_probability(output_tokens, tokens_per_catch)
    return _rng(seed).random() < p, p


def pick_species(roster_ids, caught, seed=None):
    """Choose which species appears.

    Weight = rarity x (1 for unseen, DUPLICATE_WEIGHT for already-caught), so a
    new species always beats a duplicate of equal rarity while duplicates stay
    reachable. Returns None only if the roster is empty.
    """
    ids = [int(i) for i in roster_ids]
    if not ids:
        return None
    caught = set(int(c) for c in caught)

    weights = []
    for pid in ids:
        w = RARITY.get(pid, 1.0)
        if pid in caught:
            w *= DUPLICATE_WEIGHT
        weights.append(w)

    total = sum(weights)
    if total <= 0:
        return _rng(seed).choice(ids)

    # Manual cumulative walk: random.choices is unavailable on older Pythons and
    # this keeps behaviour identical for a given seed.
    target = _rng(seed).random() * total
    upto = 0.0
    for pid, w in zip(ids, weights):
        upto += w
        if upto >= target:
            return pid
    return ids[-1]


def stable_seed(*parts):
    """Deterministic seed from arbitrary parts, for reproducible tests."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], "big")
