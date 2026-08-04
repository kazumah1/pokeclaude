---
name: pokedex
description: Browse the PokeClaude Pokedex — every Pokemon caught across all sessions. Use when the user types /pokedex, asks to see their Pokedex or collection, asks which Pokemon they have caught, asks about a specific Pokemon they own, or asks about shinies they have caught.
---

# Pokedex

Run this command:

```bash
for d in "$POKECLAUDE_ROOT" "$CODEX_PLUGIN_ROOT" "$PLUGIN_ROOT" "$CLAUDE_PLUGIN_ROOT" "$PWD" \
         "$HOME/pokeclaude" "$HOME/proj/pokeclaude" "$HOME/src/pokeclaude"; do
  for sub in "plugin/scripts" "scripts"; do
    if [ -n "$d" ] && [ -f "$d/$sub/pokedex.py" ]; then
      python3 "$d/$sub/pokedex.py" $ARGUMENTS; exit 0
    fi
  done
done
echo "pokeclaude: could not locate pokedex.py -- set POKECLAUDE_ROOT to the repo" >&2
```

Substitute the user's flags for `$ARGUMENTS`, or omit it for the default view. If
none of those paths match, set `POKECLAUDE_ROOT` to wherever the repo is cloned —
it is the directory containing `plugin/scripts/pokedex.py`.

## If the output contains a `![pokedex](...)` line

Reply with **that line, copied exactly, and nothing else**. Not in a code fence,
not with the path altered, not with a sentence before or after it.

That is the whole reply. It renders the Pokedex as a real image in the chat panel,
in full colour, which the escape-stripped tool output cannot do. Anything else in
the message pushes the art down; a code fence stops it rendering at all.

## Otherwise

Reply with **one short line and nothing more** — for example "Here's your
Pokedex." The command's output already shows the sprites, counts, names, rarity and
page number, and it is displayed to the user directly.

Do not list the Pokemon, restate the counts or progress, describe the sprites,
remark that nothing changed, suggest another flag, or explain what the command did.
The panel says all of it already, and repeating it in text buries the art.

The one exception is a question the output genuinely cannot answer, such as "which
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
| `--scale 1\|2\|3\|4` | sprite size: 1 = 64px, 2 = 32px, 3 = 21px, 4 = 16px (default). `--scale 1` on `--id` almost always saves the hook output to a file and shows a duplicate preview beneath the art -- accepted tradeoff for real 64px detail |

Flags combine, e.g. `--project --stats` or `--shiny --project`.

If the user names a Pokemon rather than a number, look up its dex number in
`plugin/assets/pokemon.json` and pass `--id`.

To release Pokemon, use the `pokeclaude-release` skill instead.
