---
description: Trade Pokémon with a friend — gift one to a code, claim a code you're sent
argument-hint: "[gift <name-or-id> | claim <code>]"
---

Trade Pokémon with another person by passing a short text **code**. There is no
server, no account, and nothing to set up — you paste the code into whatever chat
you already use.

Run every action as a Bash call:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT}}/scripts/trade.py" <args>
```

## Starting from `/trade <arg>`

- `gift <name-or-id>` → run `gift <name-or-id>`. This removes **one** copy of that
  Pokémon from your Pokédex and prints a `POKETRADE-…` code. Give the code to your
  friend. Report which Pokémon left and show them the code to send.
- `claim <code>` → run `claim <code>`. If the JSON has `received`, narrate
  `✨ Received <name>!`; if it has an `error`, relay it plainly.

## How it works, and its one honest limit

Gifting **releases your copy the moment the code is created** — even if you never
send it. That is the safe direction: your copy is gone before the code can be
claimed, so **gifting never duplicates a Pokémon on your side**; the worst case is
a code you generate and never share (that copy is gone).

This is a **trust-based** feature for friends. A code is plain text, so it *can* be
claimed more than once or forwarded to several people, each of whom would receive a
copy. Claiming the **same** code twice on the **same** machine is refused as a
courtesy, but nothing stops a determined person from spreading a code around.
Truly preventing that would need a shared server, which this feature deliberately
does not use. Trade with people you trust.
