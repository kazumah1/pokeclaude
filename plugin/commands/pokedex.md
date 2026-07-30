---
description: Browse your PokeClaude Pokedex — every Pokemon caught across all your Claude sessions
---

Run the Pokedex viewer:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pokedex.py" $ARGUMENTS
```

**Do NOT reproduce the script's output in your reply.** A `PostToolUse` hook already
re-emits it as a `systemMessage`, which is the only channel that preserves the truecolour
escapes — text you write is treated as content and has its VT control characters stripped,
so relaying it would print a second, monochrome copy of art the user can already see in
colour.

After running it, say nothing about the sprites themselves. At most add one short line of
genuinely new information: a milestone worth noting, an answer to what the user actually
asked, or a suggested next flag. Silence is a fine response.

Useful arguments to pass through when the user asks:

- (none) — first page of caught Pokemon
- `--page N` — a specific page
- `--all` — include uncaught entries as dim silhouettes
- `--id N` — large detail view for one species, at full 64px
- `--stats` — progress summary only, no art
- `--dupes` — full duplicate list, most-caught first
- `--project` — only Pokemon caught while working in this project
- `--scale 1` — full 64px sprites, 2 = 32px, 3 = 21px (grid default)

`--project` scopes to the current repo (git toplevel, else the working directory), so it
answers "how has my luck been on *this* project". It combines with the other flags, e.g.
`--project --stats`.

If the user asks about a Pokemon by name rather than number, look up its dex number in
`${CLAUDE_PLUGIN_ROOT}/assets/pokemon.json` and pass `--id`.

To release Pokemon, use `/pokeclaude:pokeclaude-release` — not this command.
