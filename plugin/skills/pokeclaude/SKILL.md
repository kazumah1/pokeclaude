---
name: pokeclaude
description: Show or change how often PokeClaude Pokemon appear. Use when the user types /pokeclaude, asks about the catch rate or spawn rate, says catches are too frequent or too rare, or asks to set light, normal or strict difficulty.
---

# PokeClaude settings

Show or change the catch rate, then reply with one short line, e.g. "Catch rate is
set." The command's output already lists the active setting and all three presets,
so do not restate them.

```bash
# Locate config.py, then run it. The search is done in Python rather than with
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
        p = os.path.join(d, sub, "config.py") if d else ""
        if p and os.path.isfile(p):
            print(p); sys.exit()
# Marketplace installs land in a per-agent cache no variable points at.
# Newest first, so an upgrade wins over the version it replaced.
for pat in ("~/.codex/plugins/cache/*/*/*/scripts/config.py",
            "~/.claude/plugins/cache/*/*/*/scripts/config.py",
            "~/.cursor/plugins/cache/*/*/*/scripts/config.py",
            "~/.kiro/plugins/cache/*/*/*/scripts/config.py",
            "~/.claude/plugins/marketplaces/*/plugin/scripts/config.py"):
    seen += glob.glob(os.path.expanduser(pat))
if seen:
    print(max(seen, key=os.path.getmtime))
')
if [ -n "$S" ]; then
  POKECLAUDE_AGENT=1 python3 "$S" $ARGUMENTS
else
  echo "pokeclaude: could not locate config.py -- set POKECLAUDE_ROOT to the repo" >&2
fi
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
