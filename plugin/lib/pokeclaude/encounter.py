"""Catch-rate model and species selection.

One roll per turn, where a turn is exactly what the user experiences as one: the
tokens the assistant produced between their prompt and the end of its response.

Rate is calibrated by replaying real turns through turn_probability rather than
by guessing or dividing aggregate totals. Across 5,057 turns from 157 sessions
(30,330 minutes of active work) the current constants yield one catch per ~72
minutes of active work. Real turns are far larger than intuition suggests --
median 5,907 output tokens, p90 32,558, max 338,263 -- which is why an assumed
"typical turn" is a bad basis for tuning.

Sessions are strongly bimodal: 228 real sessions had a median of 2 turns, but
those with real work behind them (>=5 turns) had a median of 17 and a p90 of 123.
Tuning against the overall median therefore describes almost none of the actual
usage; the >=5-turn population is the one that matters.

Three measurement traps, each of which produced a wrong constant here first:

  1. Claude Code writes one transcript record per content block and repeats the
     message's FINAL output_tokens on every one, so summing per record
     over-counts by 2-3x. Always deduplicate by message id. An earlier
     calibration used ~3,300 tok/min from naive summing; the reader had the same
     bug, and the two errors partly cancelled -- which is precisely why it
     survived a first round of testing.
  2. "Tokens per minute" depends entirely on the denominator. Wall-clock across a
     session gives ~1,070 tok/min; excluding idle gaps of over five minutes gives
     ~2,090. Active time is the right basis, since a session left open overnight
     should not count as time spent working.
  3. Tool results are recorded as `type: "user"`, so a turn boundary must not be
     drawn at every one of them or a long agentic turn is split into dozens.

Because of traps 2 and 3, retune by replaying turns using the hook's own turn
splitter, never via a tokens-per-minute shortcut.

Odds are derived per-turn from real `output_tokens` in the transcript, so a long
grinding turn genuinely improves your chances and an idle one does not.

Duplicates are possible but deliberately rarer than new species: a duplicate
roll is kept at DUPLICATE_WEIGHT of a new one, so the dex keeps filling in while
still handing out the occasional repeat. As the dex nears completion the
remaining-new pool shrinks, so duplicates naturally dominate the tail instead of
catches drying up entirely.

Roster size does not affect the catch RATE -- only what a catch turns out to be.
Extending from 386 to 1025 species therefore left every constant here alone; it
divides each species' encounter share by ~2.6 and makes a complete dex a much
longer project, which is the intent.
"""
import hashlib
import os
import random

# Difficulty presets, in turn tokens per catch. Calibrated against a real
# 589k-token, 147-turn session so the numbers describe sessions rather than
# abstract token counts:
#
#   light   ~2 catches in such a session
#   normal  ~1 catch      (the point where a catch reads as an event)
#   strict  ~0.5 catches  (a genuine surprise)
#
# Beware of specifying these as "1 per N tokens" without checking N against a
# real session: a 589k-token session makes "1 per 100k" mean six catches, which
# sounds rare and is not.
PRESETS = {
    "light": 300_000,
    "normal": 600_000,
    "strict": 1_200_000,
}
DEFAULT_PRESET = "normal"

# Resolved at import from the user's config; PRESETS[DEFAULT_PRESET] is the
# fallback whenever the file is missing or unreadable.
TOKENS_PER_CATCH = PRESETS[DEFAULT_PRESET]

# A duplicate species is this much as likely as an unseen one.
DUPLICATE_WEIGHT = 0.25

# Ceiling on any single turn: one enormous turn should feel lucky, not
# inevitable. At 0.25 it binds above 13,750 tokens (~26% of turns), while an
# ordinary turn is untouched -- the 5,907-token median still rolls ~11%.
#
# Worth knowing before reaching for this to tame long sessions: it barely can.
# Measured over 228 real sessions, 71% of the catches in a p90-by-time session
# come from ORDINARY turns, not capped ones, because such sessions are long by
# turn count (median 107 turns over 580 active minutes) rather than by turn size.
# The cap shaves a tail, not the bulk. Trying to restore the overall rate
# afterwards by lowering TOKENS_PER_CATCH pushes marathon totals straight back up
# (13.2 -> 16.4 catches), so the two knobs work against each other. Scale the
# whole curve with TOKENS_PER_CATCH; use this only to bound the extremes.
MAX_TURN_PROBABILITY = 0.25

# Legendaries/mythicals are rarer. Everything unlisted has weight 1.0.
#
# Membership comes from PokeAPI's own `is_legendary` / `is_mythical` species
# flags rather than from judgement calls. Those flags reproduce the original
# hand-written Gen 1-3 table exactly -- all 21 entries, with mythicals landing on
# 0.04 and legendaries between 0.05 and 0.12 -- which is what makes them
# trustworthy enough to extend the roster to 1025 with.
#
# Weights are expressed as sets rather than 94 literal dict entries so the
# *reason* for each weight survives. A flat table would leave the next person
# adding Gen 10 with no way to tell why Zacian sits at 0.06 and Regieleki at
# 0.12.
MYTHICAL_IDS = frozenset({
    151, 251, 385, 386,                          # gen 1-3
    489, 490, 491, 492, 493, 494,                # gen 4
    647, 648, 649,                               # gen 5
    719, 720, 721,                               # gen 6
    801, 802, 807, 808, 809,                     # gen 7
    893,                                         # gen 8
    1025,                                        # gen 9
})

# Cover/apex legendaries -- the one or two on each game's box, plus expansion
# headliners. Rarer than the trios but not as rare as a mythical.
APEX_IDS = frozenset({
    150, 249, 250, 382, 383,                     # gen 1-3
    483, 484, 487,                               # Dialga, Palkia, Giratina
    643, 644, 646,                               # Reshiram, Zekrom, Kyurem
    716, 717, 718,                               # Xerneas, Yveltal, Zygarde
    791, 792, 800,                               # Solgaleo, Lunala, Necrozma
    888, 889, 890, 898,                          # Zacian, Zamazenta, Eternatus, Calyrex
    1007, 1008, 1017, 1024,                      # Koraidon, Miraidon, Ogerpon, Terapagos
})

# Everything else PokeAPI flags legendary: trios, quartets and one-offs.
LEGENDARY_IDS = frozenset({
    144, 145, 146,                               # gen 1
    243, 244, 245,                               # gen 2
    377, 378, 379, 380, 381, 384,                # gen 3
    480, 481, 482, 485, 486, 488,                # gen 4
    638, 639, 640, 641, 642, 645,                # gen 5
    772, 773, 785, 786, 787, 788, 789, 790,      # gen 7
    891, 892, 894, 895, 896, 897, 905,           # gen 8
    1001, 1002, 1003, 1004, 1014, 1015, 1016,    # gen 9
})

# Two Gen 3 weights predate the banding above and are pinned so existing
# Pokedexes keep the odds they were filled at.
_LEGACY_WEIGHTS = {380: 0.10, 381: 0.10, 384: 0.05}

RARITY = {}
for _pid in MYTHICAL_IDS:
    RARITY[_pid] = 0.04
for _pid in APEX_IDS:
    RARITY[_pid] = 0.06
for _pid in LEGENDARY_IDS:
    RARITY[_pid] = 0.12
RARITY.update(_LEGACY_WEIGHTS)
del _pid


def resolve_preset(name):
    """Map a preset name to its tokens-per-catch, tolerating junk.

    Anything unrecognised falls back to the default rather than raising, because
    this is read by a hook that must never break a turn over a typo'd config.
    """
    return PRESETS.get(str(name or "").strip().lower(), PRESETS[DEFAULT_PRESET])


def configured_tokens_per_catch(config=None):
    """Tokens per catch from the user's config, or the default.

    Accepts an explicit numeric `tokens_per_catch` override for anyone who wants
    a rate between the presets; otherwise reads `preset`.
    """
    cfg = config or {}
    override = cfg.get("tokens_per_catch")
    if isinstance(override, (int, float)) and override > 0:
        return int(override)
    return resolve_preset(cfg.get("preset"))


def turn_probability(output_tokens, tokens_per_catch=None):
    """Chance that a turn of `output_tokens` yields a catch."""
    if output_tokens <= 0:
        return 0.0
    if tokens_per_catch is None:
        tokens_per_catch = TOKENS_PER_CATCH
    return min(MAX_TURN_PROBABILITY, float(output_tokens) / float(tokens_per_catch))


def _rng(seed=None):
    """Seedable RNG. Unseeded draws use os.urandom so parallel sessions that
    start in the same second cannot roll identically."""
    if seed is not None:
        return random.Random(seed)
    return random.Random(int.from_bytes(os.urandom(8), "big"))


def roll(output_tokens, seed=None, tokens_per_catch=None):
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


# --- rarity, for display ----------------------------------------------------
# Tiers are cut on the RARITY multiplier, not on encounter share, because share
# depends on roster size: adding Gen 4-9 would push every species' share down and
# silently reclassify the whole dex. The multiplier is an intrinsic property.
#
# The roster is genuinely bimodal -- 365 species at multiplier 1.0 and 21
# legendaries between 0.04 and 0.12 -- so inventing five evenly spaced tiers
# would be fiction. These four describe what actually exists, and MYTHICAL
# separates the true one-offs (Mew, Celebi, Jirachi, Deoxys at <=0.05) from the
# merely legendary birds and beasts.
# The MYTHICAL cut is 0.045 rather than 0.05 so it lands strictly between the
# mythical weight (0.04) and the lowest legendary one (Rayquaza, pinned at 0.05).
# At an inclusive 0.05 boundary Rayquaza was labelled MYTHICAL, which contradicts
# its species flag; moving the threshold fixes the label without altering anyone's
# odds.
TIERS = (
    (0.045, "MYTHICAL"),
    (0.15, "LEGENDARY"),
    (0.99, "RARE"),
    (1e9, "COMMON"),
)


def encounter_share(species_id, roster_ids):
    """This species' share of all encounters, as a percentage.

    Computed on an EMPTY dex, so the number is a stable property of the species
    rather than something that drifts as the player's collection fills. (With a
    full dex every weight is scaled by DUPLICATE_WEIGHT, which cancels out and
    leaves the same shares anyway.)
    """
    ids = [int(i) for i in roster_ids]
    if not ids:
        return 0.0
    total = sum(RARITY.get(p, 1.0) for p in ids)
    if total <= 0:
        return 0.0
    return 100.0 * RARITY.get(int(species_id), 1.0) / total


def rarity_tier(species_id, roster_ids=None):
    """Tier label for a species, from its intrinsic rarity multiplier.

    `roster_ids` is accepted but unused: the tier does not depend on roster size,
    unlike encounter_share. It stays in the signature so callers can pass the same
    arguments to both.
    """
    mult = RARITY.get(int(species_id), 1.0)
    for limit, label in TIERS:
        if mult <= limit:
            return label
    return "COMMON"


def format_rarity(species_id, roster_ids):
    """'0.04% of encounters  ·  LEGENDARY', ready to display.

    Percentages are shown with enough precision to distinguish tiers: a
    legendary sits near 0.01% and a common near 0.29%, so two decimals are
    needed and trailing zeros are trimmed for tidiness.
    """
    share = encounter_share(species_id, roster_ids)
    if share <= 0:
        return ""
    text = ("%.3f" % share).rstrip("0").rstrip(".") if share < 0.1 else "%.2f" % share
    return "%s%% of encounters  ·  %s" % (text, rarity_tier(species_id, roster_ids))
