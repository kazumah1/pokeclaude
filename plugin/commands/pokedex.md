---
description: Browse your PokeClaude Pokedex — every Pokemon caught across all your Claude sessions
---

Run the Pokedex viewer and show the user its output.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pokedex.py" $ARGUMENTS
```

The script prints ANSI pixel art. Relay its output **verbatim** inside a fenced code
block so the escape sequences reach the terminal intact — do not summarize it,
re-describe the sprites, or strip the colour codes.

Useful arguments to pass through when the user asks:

- (none) — first page of caught Pokemon
- `--page N` — a specific page
- `--all` — include uncaught entries as dim silhouettes
- `--id N` — large detail view for one species
- `--stats` — progress summary only, no art
- `--dupes` — full duplicate list, most-caught first
- `--project` — only Pokemon caught while working in this project
- `--scale 1` — full-size 32px sprites (fewer per row)

`--project` scopes to the current repo (git toplevel, else the working directory), so it
answers "how has my luck been on *this* project". It combines with the other flags, e.g.
`--project --stats`.

If the user asks about a Pokemon by name rather than number, look up its dex number in
`${CLAUDE_PLUGIN_ROOT}/assets/pokemon.json` and pass `--id`.

To release Pokemon, use `/pokeclaude-release` — not this command.
