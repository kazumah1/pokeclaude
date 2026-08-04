---
name: pokeclaude
description: Show or change how often PokeClaude Pokemon appear. Use when the user types /pokeclaude, asks about the catch rate or spawn rate, says catches are too frequent or too rare, or asks to set light, normal or strict difficulty.
---

# PokeClaude settings

Show or change the catch rate, then reply with one short line, e.g. "Catch rate is
set." The command's output already lists the active setting and all three presets,
so do not restate them.

```bash
# 1. Where the repo or installed plugin says it is.
for d in "$POKECLAUDE_ROOT" "$CODEX_PLUGIN_ROOT" "$PLUGIN_ROOT" "$CLAUDE_PLUGIN_ROOT" "$PWD" \
         "$HOME/pokeclaude" "$HOME/proj/pokeclaude" "$HOME/src/pokeclaude"; do
  for sub in "plugin/scripts" "scripts"; do
    if [ -n "$d" ] && [ -f "$d/$sub/config.py" ]; then
      python3 "$d/$sub/config.py" $ARGUMENTS; exit 0
    fi
  done
done
# 2. Where the agent that installed us actually put it. A marketplace install
#    lands in a per-agent cache that no environment variable points at, and some
#    hosts (the Codex app) set none of the variables above at all. Newest first,
#    so an upgrade wins over the version it replaced.
for f in $(ls -1dt "$HOME"/.codex/plugins/cache/*/*/*/scripts/config.py \
                   "$HOME"/.claude/plugins/cache/*/*/*/scripts/config.py \
                   "$HOME"/.cursor/plugins/cache/*/*/*/scripts/config.py \
                   "$HOME"/.claude/plugins/marketplaces/*/plugin/scripts/config.py 2>/dev/null); do
  python3 "$f" $ARGUMENTS; exit 0
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

## Art

| Flag | Effect |
|---|---|
| `--inline on\|off\|auto` | put the art in the reply as a markdown image. Automatic in Cursor; turn it **on** for the Codex app, and leave it off for the Codex CLI, which is a terminal and renders the art itself. |
| `--image-tab on\|off\|auto` | draw catches as a PNG at all. On by default wherever the agent can show one; `off` restores the text banner everywhere. |
| `--mono on\|off\|auto` | solid silhouettes instead of colour, for surfaces that strip ANSI and cannot show an image either. |

Only turn tokens count — input + output, never cache. Settings live in
`~/.claude/pokeclaude/config.json` and apply to every session and every host.
