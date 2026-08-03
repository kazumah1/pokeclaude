---
name: trade
description: Trade Pokémon with another person by passing a short text code — gift one Pokémon to a code, or claim a code someone sent you. Use when the user wants to give a Pokémon to a friend, send or receive a trade, or claim a POKETRADE code.
---

# Pokémon Trading

Move a Pokémon between two people with a pasteable code. No server, no accounts,
no setup. Run each action as a Bash call and narrate the JSON result:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT}}/scripts/trade.py" <args>
```

## Commands

- `gift <name-or-id>` — removes one copy of that Pokémon from your Pokédex and
  prints a `POKETRADE-…` code to send to a friend.
- `claim <code>` — adds the Pokémon from a `POKETRADE-…` code to your Pokédex.

## What to tell the user

- **Gifting releases your copy immediately** (even if the code is never sent) — your
  copy is gone before the code can be claimed, so **gifting never duplicates a
  Pokémon on your side**.
- **It's trust-based.** A code is plain text: claiming the same code twice on one
  machine is refused, but a code can be forwarded to several people, each receiving
  a copy. There is no server to prevent this by design. Trade with people you trust.
- On `claim`, relay `✨ Received <name>!` on success, or the `error` message as-is.
