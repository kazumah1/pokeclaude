---
name: pokeclaude
description: Show or change how often PokeClaude Pokemon appear. Use when the user types /pokeclaude, asks about the catch rate or spawn rate, says catches are too frequent or too rare, or asks to set light, normal or strict difficulty.
---

# PokeClaude settings

Show or change the catch rate, then reply with one short line, e.g. "Catch rate is
set." The command's output already lists the active setting and all three presets,
so do not restate them.

```bash
for d in "$POKECLAUDE_ROOT" "$CODEX_PLUGIN_ROOT" "$PLUGIN_ROOT" "$CLAUDE_PLUGIN_ROOT" "$PWD" \
         "$HOME/pokeclaude" "$HOME/proj/pokeclaude" "$HOME/src/pokeclaude"; do
  for sub in "plugin/scripts" "scripts"; do
    if [ -n "$d" ] && [ -f "$d/$sub/config.py" ]; then
      python3 "$d/$sub/config.py" $ARGUMENTS; exit 0
    fi
  done
done
echo "pokeclaude: could not locate config.py -- set POKECLAUDE_ROOT to the repo" >&2
```

Run with no arguments to show the current setting.

## Presets

| Preset | Rate | Catches per session |
|---|---|---|
| `light` | 1 per 300k tokens | ~2 |
| `normal` | 1 per 600k tokens | ~1 (default) |
| `strict` | 1 per 1.2M tokens | ~0.5 |

`--tokens N` sets an exact rate between or beyond the presets, and overrides the
preset until one is chosen again.

Only turn tokens count — input + output, never cache. Settings live in
`~/.claude/pokeclaude/config.json` and apply to every session and every host.
