---
description: Release a Pokemon (or all of them) from your PokeClaude Pokedex
argument-hint: "<name|number|all> [--project] [--confirm]"
---

Release Pokemon from the Pokedex. **This deletes collection data and cannot be undone**,
so it runs in two steps.

**Step 1 — always dry-run first.** Run without `--confirm` to show the user exactly what
would be removed. The script prints the consequences and exits 2 without changing
anything:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/release.py" $ARGUMENTS
```

**Step 2 — confirm with the user, then re-run with `--confirm`.** Do NOT add `--confirm`
on your own initiative. Only add it after the user has seen the dry run and explicitly
agreed, or if their original request already said something unambiguous like "yes, delete
everything" / "release all my pokemon, I'm sure".

Do not relay the output — a `PostToolUse` hook already re-emits it in colour. After a dry
run, the only thing worth adding is the question itself: whether to proceed. After a
`--confirm` run, say nothing; the panel reports what was removed.

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
- `2` — dry run; nothing was changed, awaiting `--confirm`

If the user wants to wipe everything and start over, `all --confirm` is the full reset.
If they only want to reset one project's stats while keeping their collection, add
`--project`.
