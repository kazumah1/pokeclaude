---
name: marketplace
description: Barter Pokémon with other people on a self-hosted marketplace — deposit a Pokémon, list it, offer one of yours for a listing, accept a swap, withdraw. Use when the user wants to trade on a marketplace, list/browse Pokémon for barter, make or accept an offer, or deposit/withdraw from their vault. Dormant unless POKECLAUDE_MARKET_URL is set.
---

# Pokémon Marketplace

A self-hosted **escrow barter** marketplace. Inert until the user sets
`POKECLAUDE_MARKET_URL` (or `marketplace_url` in config) — with none set, every
command returns an `info` no-op and makes no network call. Run each action as a
Bash call and narrate the JSON:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT}}/scripts/marketplace.py" <args>
```

## Flow

1. `register <name>` once (token saved locally).
2. `deposit <name-or-id>` moves a Pokémon into your server vault (it leaves your Pokédex).
3. `list <item_id>` to offer it; others `offer <listing_id> <their_item_id>`.
4. As seller, `accept <offer_id>` → the server swaps ownership atomically.
5. `withdraw <item_id>` brings a vault Pokémon back into your Pokédex.

## What to tell the user

- **Deposit is safe-by-ordering:** the copy leaves your Pokédex before the server
  records it, so it's never in both places. If a deposit is interrupted, run
  `reconcile` — it confirms the deposit or restores your copy; nothing is duplicated.
- **Trades are atomic:** an accept swaps both Pokémon in one server transaction.
- **Trust-on-deposit:** the server can't verify a deposited Pokémon was really caught.
  Use a server run by people you trust.
