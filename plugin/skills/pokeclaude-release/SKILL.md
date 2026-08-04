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
# Locate release.py, then run it. The search is done in Python rather than with
# shell globs on purpose: an unmatched glob is a fatal error in zsh ("no matches
# found"), which aborted this whole command in Kiro, while bash passes it
# through. Python has no such disagreement with itself.
S=$(python3 -c '
import glob, os, sys
seen = []
for d in [os.environ.get(v, "") for v in
          ("POKECLAUDE_ROOT", "CODEX_PLUGIN_ROOT", "PLUGIN_ROOT",
           "CLAUDE_PLUGIN_ROOT")] + [os.getcwd()] + [
          os.path.expanduser(p) for p in
          ("~/pokeclaude", "~/proj/pokeclaude", "~/src/pokeclaude")]:
    for sub in ("plugin/scripts", "scripts"):
        p = os.path.join(d, sub, "release.py") if d else ""
        if p and os.path.isfile(p):
            print(p); sys.exit()
# Marketplace installs land in a per-agent cache no variable points at.
# Newest first, so an upgrade wins over the version it replaced.
for pat in ("~/.codex/plugins/cache/*/*/*/scripts/release.py",
            "~/.claude/plugins/cache/*/*/*/scripts/release.py",
            "~/.cursor/plugins/cache/*/*/*/scripts/release.py",
            "~/.kiro/plugins/cache/*/*/*/scripts/release.py",
            "~/.claude/plugins/marketplaces/*/plugin/scripts/release.py"):
    seen += glob.glob(os.path.expanduser(pat))
if seen:
    print(max(seen, key=os.path.getmtime))
')
if [ -n "$S" ]; then
  POKECLAUDE_AGENT=1 python3 "$S" $ARGUMENTS
else
  echo "pokeclaude: could not locate release.py -- set POKECLAUDE_ROOT to the repo" >&2
fi
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
