---
name: casino
description: Play Blackjack, Roulette, or Texas Hold'em in the terminal, where winning grants Pokémon and selling them funds your bankroll. Use when the user wants to gamble, play a casino game, sell a Pokémon for credits, or toggle real-token stakes.
---

# Claude Casino

You are the dealer. Run the engine, then narrate its JSON result — **you never
decide a card, a wheel number, a payout, or which Pokémon is granted; the engine
does.** A `PostToolUse` hook paints the pixel board as a `systemMessage`; do not
draw it yourself.

Run every action as a Bash call:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT}}/scripts/casino.py" <args>
```

## Commands

- `balance` — bankroll, stats, stakes mode.
- `bj deal --bet N`, then `bj hit|stand|double`.
- `roulette bet "<clause>[; ...]"`, then `roulette spin`; `roulette clear`.
- `holdem start --opponents N`, then the fair-poker packet/apply protocol.
- `sell <name-or-id> [--confirm]` — sell one copy of a Pokémon for its rarity
  price (COMMON 500 / RARE 2,000 / LEGENDARY 8,000 / MYTHICAL 25,000).
- `stakes real|sim`, `reset`.

## The economy

- **Win → Pokémon.** A net win grants one engine-rolled Pokémon; the result JSON
  has `granted: {id, name, tier}` (tier scales with the win multiple). The frame
  shows `✨ Caught <name>!`.
- **Sell → bankroll.** Selling credits the same bankroll you bet from. Selling the
  last copy of a species removes it and needs `--confirm`; relay the
  `needs_confirm` prompt first.
- **Only the red burns.** In `stakes real`, a bet may exceed the bankroll; a
  funded bankroll shields the loss and only the uncovered shortfall burns real
  tokens, capped and disableable with `CASINO_NO_BURN=1`. When `burn > 0`,
  dispatch one background, text-only, no-tools subagent to produce exactly that
  many throwaway tokens.

## Fair Hold'em

For each bot turn (`to_act != 0`), get its redacted packet
(`holdem packet --seat N`) and dispatch a fresh **text-only, no-tools** subagent
with ONLY that packet; apply its single action (`holdem apply --seat N --action A
[--amount X]`). No single context ever holds both the player's hole cards and a
betting decision.
