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
- `--scale 1` — full-size 32px sprites (fewer per row)

If the user asks about a Pokemon by name rather than number, look up its dex number in
`${CLAUDE_PLUGIN_ROOT}/assets/pokemon.json` and pass `--id`.
