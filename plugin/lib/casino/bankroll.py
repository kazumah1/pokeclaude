"""Bankroll economics: how much a loss burns and how much work earns.

No code can deduct from a real Anthropic token allowance, so a loss is made to
cost real tokens elsewhere (a background burn agent spawned by Claude). This
module only decides the *amount*; spawning is Claude's job. Burning is opt-in
(config.stakes == "real") and always overridable by the CASINO_NO_BURN env
kill-switch, and clamped by a per-hand cap so one bad hand cannot nuke a quota.
"""
import math

START_STAKE = 10000
DEFAULT_BURN_CAP = 20000
DEFAULT_EARN_MULTIPLIER = 1.0


def default_config():
    return {
        "stakes": "sim",
        "burn_cap": DEFAULT_BURN_CAP,
        "earn_multiplier": DEFAULT_EARN_MULTIPLIER,
    }


def resolve_burn(loss_tokens, config, env):
    """Real tokens to burn for a loss. 0 unless real-mode and kill-switch off."""
    if loss_tokens <= 0:
        return 0
    if "CASINO_NO_BURN" in env:
        return 0
    if config.get("stakes") != "real":
        return 0
    cap = int(config.get("burn_cap", DEFAULT_BURN_CAP))
    return min(int(loss_tokens), cap)


def credit_amount(turn_tokens, config):
    """Bankroll credit for a turn's real token usage."""
    if turn_tokens <= 0:
        return 0
    mult = float(config.get("earn_multiplier", DEFAULT_EARN_MULTIPLIER))
    return int(math.floor(turn_tokens * mult))
