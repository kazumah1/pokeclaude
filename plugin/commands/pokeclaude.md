---
description: PokeClaude settings — set how often Pokemon appear
argument-hint: "[light|normal|strict] · [--tokens N]"
---

Show or change the catch rate:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/config.py" $ARGUMENTS
```

Run it and then STOP. Emit no text at all. A `PostToolUse` hook re-emits the output as a
`systemMessage` — the only channel that keeps the truecolour escapes — and the panel already
shows the active setting and all three presets. Treat this as a bare shell command; zero
words is the correct response.

## Presets

| Preset | Rate | Catches per session |
|---|---|---|
| `light` | 1 per 300k tokens | ~2 |
| `normal` | 1 per 600k tokens | ~1 (default) |
| `strict` | 1 per 1.2M tokens | ~0.5 |

"Per session" is measured against a real 589k-token, 147-turn session. That reference
matters: stating a rate as "1 per 100k tokens" sounds rare but would mean roughly six
catches in a session that size.

`--tokens N` sets an exact rate for anyone who wants something between or beyond the
presets. It overrides the preset until a preset is chosen again.

Only turn tokens count — input + output, never cache. Cache reads outnumber real output by
several hundred times, so counting them would tie the rate to context size rather than to
work done.

Settings live in `~/.claude/pokeclaude/config.json` and apply to every Claude session.
