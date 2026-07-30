---
description: Browse your PokeClaude Pokedex — every Pokemon caught across all your Claude sessions
argument-hint: "[--id <name|number> · --all · --stats|--dupes · --project · --page N · --scale 1|2|3]"
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

**Say nothing after running it.** The hook output IS the response. Do not describe the
sprites, restate the counts, note that nothing changed, or suggest another flag — the user
can read the panel and knows the flags.

The only exception is a direct question the output does not already answer (e.g. "which of
these is rarest?"). Otherwise reply with nothing at all.

Useful arguments to pass through when the user asks:

- (none) — first page of caught Pokemon
- `--page N` — a specific page
- `--all` — include uncaught entries as dim silhouettes
- `--id N` — large detail view for one species (32px)
- `--stats` — progress summary only, no art
- `--dupes` — full duplicate list, most-caught first
- `--project` — only Pokemon caught while working in this project
- `--scale 1` — full 64px sprites. Renders 12-26KB depending on the species, which
  straddles the size at which Claude Code persists output to a file and shows only a
  preview; whether it appears inline is therefore not predictable. Pass it when the user
  explicitly asks for maximum detail, and expect they may need ctrl+o.

`--project` scopes to the current repo (git toplevel, else the working directory), so it
answers "how has my luck been on *this* project". It combines with the other flags, e.g.
`--project --stats`.

If the user asks about a Pokemon by name rather than number, look up its dex number in
`${CLAUDE_PLUGIN_ROOT}/assets/pokemon.json` and pass `--id`.

To release Pokemon, use `/pokeclaude:pokeclaude-release` — not this command.
