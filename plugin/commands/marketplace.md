---
description: Trade Pokémon on a marketplace — deposit, list, offer, accept, withdraw
argument-hint: "[register <name> | deposit <name> | list <item_id> | browse | offer <listing_id> <item_id> | accept <offer_id> | vault | withdraw <item_id>]"
---

Barter Pokémon with other people through a self-hosted marketplace server. This is
**dormant by default**: it does nothing until you point it at a server with
`POKECLAUDE_MARKET_URL=https://…` (or set `marketplace_url` in pokeclaude config).

Run every action as a Bash call:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT}}/scripts/marketplace.py" <args>
```

## Commands

- `register <name>` — create an account; the server returns a token, saved locally.
- `deposit <name-or-id>` — move one Pokémon from your Pokédex into your server vault.
- `withdraw <item_id>` — bring a vault Pokémon back into your Pokédex.
- `list <item_id> [--note ...]` — put a deposited Pokémon up for barter.
- `browse` — see open listings. `vault` — see your items/listings/offers.
- `offer <listing_id> <your_item_id>` — offer one of your deposited Pokémon for a listing.
- `accept <offer_id>` / `decline <offer_id>` — as the seller, resolve an offer.
- `cancel <listing_id>` — take your listing down. `retract <offer_id>` — pull your offer.
- `reconcile` — finish any deposit interrupted by a network error (nothing is lost).

## How it stays safe

Depositing removes the Pokémon from your Pokédex **before** the server records it,
so a Pokémon is never in your Pokédex and the market at once. If a deposit is
interrupted, run `reconcile` — it either confirms the deposit landed or restores your
copy. Trades are settled atomically by the server (you can't be half-swapped).

## Honest limit

The server can't verify a deposited Pokémon was legitimately caught (catches happen
locally), so this is trust-based on provenance. Use a server run by people you trust.
