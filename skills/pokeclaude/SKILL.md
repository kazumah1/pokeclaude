---
name: pokeclaude
description: Show or change how often PokeClaude Pokemon appear. Use when the user types /pokeclaude, asks about the catch rate or spawn rate, says catches are too frequent or too rare, or asks to set light, normal or strict difficulty.
---

# PokeClaude settings

Show or change the catch rate, then STOP. Emit no text — the panel already shows the
active setting and all three presets.

```bash
for d in "$POKECLAUDE_ROOT" "$PWD" "$HOME/pokeclaude" "$HOME/proj/pokeclaude" "$HOME/src/pokeclaude"; do
  [ -n "$d" ] && [ -f "$d/plugin/scripts/config.py" ] && { python3 "$d/plugin/scripts/config.py" $ARGUMENTS; break; }
done
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
