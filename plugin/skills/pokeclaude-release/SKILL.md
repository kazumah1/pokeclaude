---
name: pokeclaude-release
description: Release a Pokemon, or all of them, from the PokeClaude Pokedex. Use when the user types /pokeclaude-release, asks to release or remove a Pokemon, asks to reset or wipe their Pokedex, or asks to start their collection over.
---

# Release

**This deletes collection data and cannot be undone**, so it runs in two steps.

## Step 1 — always dry-run first

Run without `--confirm`. The script prints exactly what would be removed and exits
2 without changing anything:

```bash
# 1. Where the repo or installed plugin says it is.
for d in "$POKECLAUDE_ROOT" "$CODEX_PLUGIN_ROOT" "$PLUGIN_ROOT" "$CLAUDE_PLUGIN_ROOT" "$PWD" \
         "$HOME/pokeclaude" "$HOME/proj/pokeclaude" "$HOME/src/pokeclaude"; do
  for sub in "plugin/scripts" "scripts"; do
    if [ -n "$d" ] && [ -f "$d/$sub/release.py" ]; then
      python3 "$d/$sub/release.py" $ARGUMENTS; exit 0
    fi
  done
done
# 2. Where the agent that installed us actually put it. A marketplace install
#    lands in a per-agent cache that no environment variable points at, and some
#    hosts (the Codex app) set none of the variables above at all. Newest first,
#    so an upgrade wins over the version it replaced.
for f in $(ls -1dt "$HOME"/.codex/plugins/cache/*/*/*/scripts/release.py \
                   "$HOME"/.claude/plugins/cache/*/*/*/scripts/release.py \
                   "$HOME"/.cursor/plugins/cache/*/*/*/scripts/release.py \
                   "$HOME"/.claude/plugins/marketplaces/*/plugin/scripts/release.py 2>/dev/null); do
  python3 "$f" $ARGUMENTS; exit 0
done
echo "pokeclaude: could not locate release.py -- set POKECLAUDE_ROOT to the repo" >&2
```

## Step 2 — confirm, then re-run with `--confirm`

Do **not** add `--confirm` on your own initiative. Only add it after the user has
seen the dry run and agreed, or if their original request was already unambiguous
("yes, delete everything", "release all my pokemon, I'm sure").

After a dry run, the only thing worth adding is the question: whether to proceed.
After a `--confirm` run, say nothing — the panel reports what was removed.

## Arguments

| Form | Effect |
|---|---|
| `pikachu` | one species, by name |
| `25` | one species, by dex number |
| `all` | the entire Pokedex |
| `--project` | limit to this project's records; the global Pokedex is untouched |
| `--confirm` | actually perform the release |

## Exit codes

- `0` — done, or nothing to do (species not in the Pokedex)
- `1` — unknown Pokemon name, or the lock was unavailable (nothing changed)
- `2` — dry run; nothing changed, awaiting `--confirm`

`all --confirm` is the full reset. To reset only one project's stats while keeping
the collection, add `--project`.
