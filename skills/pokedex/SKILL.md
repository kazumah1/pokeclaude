---
name: pokedex
description: Browse the PokeClaude Pokedex — every Pokemon caught across all sessions. Use when the user types /pokedex, asks to see their Pokedex or collection, asks which Pokemon they have caught, asks about a specific Pokemon they own, or asks about shinies they have caught.
---

# Pokedex

Run exactly one command and then STOP. Emit no text at all — before or after.

```bash
for d in "$POKECLAUDE_ROOT" "$PWD" "$HOME/pokeclaude" "$HOME/proj/pokeclaude" "$HOME/src/pokeclaude"; do
  [ -n "$d" ] && [ -f "$d/plugin/scripts/pokedex.py" ] && { python3 "$d/plugin/scripts/pokedex.py" $ARGUMENTS; break; }
done
```

Substitute the user's flags for `$ARGUMENTS`, or omit it for the default view. If
none of those paths match, set `POKECLAUDE_ROOT` to wherever the repo is cloned —
it is the directory containing `plugin/scripts/pokedex.py`.

Treat this as a bare shell command the user ran themselves. Your turn ends when the
command returns. Zero words is the correct and expected response.

The panel is self-describing — it shows the counts, names, rarity and page number.
Do not describe the sprites, restate counts or progress, remark that nothing
changed, observe that a species is or is not caught, suggest another flag, or
confirm that the command ran.

The only exception is a question the panel genuinely cannot answer, such as "which
of these is rarest?" — then answer just that, in one line.

## Arguments

| Flag | Effect |
|---|---|
| *(none)* | first page of caught Pokemon |
| `--page N` | a specific page |
| `--all` | include uncaught entries as dim silhouettes |
| `--id N` | large detail view for one species |
| `--shiny` | only the shinies the user has caught |
| `--normal` | with `--id`, ordinary colours of a species they own a shiny of |
| `--stats` | progress summary, no art |
| `--dupes` | full duplicate list, most-caught first |
| `--project` | only Pokemon caught while working in this project |
| `--scale 1\|2\|3` | sprite size: 1 = 64px, 2 = 32px, 3 = 21px (default) |

Flags combine, e.g. `--project --stats` or `--shiny --project`.

If the user names a Pokemon rather than a number, look up its dex number in
`plugin/assets/pokemon.json` and pass `--id`.

To release Pokemon, use the `pokeclaude-release` skill instead.
