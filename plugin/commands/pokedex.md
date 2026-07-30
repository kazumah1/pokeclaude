---
description: Browse your PokeClaude Pokedex — every Pokemon caught across all your Claude sessions
argument-hint: "[--id <name|number> · --all · --stats|--dupes · --shiny · --project · --page N · --scale 1|2|3]"
---

Run exactly one command and then STOP. Emit no text at all — before or after.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pokedex.py" $ARGUMENTS
```

Treat this as a bare shell command the user ran themselves. Your turn ends when the command
returns. Zero words is the correct and expected response.

Two reasons, both mechanical rather than stylistic:

1. A `PostToolUse` hook re-emits the stdout as a `systemMessage`, the only channel that
   preserves truecolour escapes. Text you write is content and has its VT control characters
   stripped, so any restatement appears as a second, monochrome copy of art already on
   screen in colour.
2. The panel is self-describing. It shows the counts, the names, the rarity and the page
   number. Narration adds nothing and the user has asked, repeatedly, for none.

Do not: describe the sprites, restate counts or progress, remark that nothing changed,
observe that a species is or is not caught, suggest another flag, or confirm that the
command ran.

The **only** exception is a question the panel genuinely cannot answer — "which of these is
rarest?" — and then answer just that, in one line.

Useful arguments to pass through when the user asks:

- (none) — first page of caught Pokemon
- `--page N` — a specific page
- `--all` — include uncaught entries as dim silhouettes
- `--id N` — large detail view for one species (32px)
- `--stats` — progress summary only, no art
- `--dupes` — full duplicate list, most-caught first
- `--shiny` — with `--id`, show a species' shiny colours even if you have not caught one.
  Shinies you own already render in their shiny colours automatically, marked `✧`.
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

To release Pokemon, use `/pokeclaude:release` — not this command.
