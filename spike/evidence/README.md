# Spike evidence

Two platform assumptions underpin this plugin. Both were unknown at design time and both
were settled empirically against Claude Code 2.1.220 rather than inferred from docs.

## 1. Hook `systemMessage` renders truecolor pixel art

`systemMessage-ansi-confirmed.log` is the raw payload a `PostToolUse` hook emitted.

The delivered transcript `attachment.content` preserved, byte for byte:

- `\n` newlines (13 lines, unreflowed)
- truecolor SGR escapes (`\x1b[38;2;237;28;36m`)
- Unicode half-blocks (`▀▄█`) and box-drawing
- emoji and CJK

Confirmed visually in-terminal: the colour probes showed actual red/green/blue and the
test sprite rendered as a recognizable red-and-white pokeball.

**Conclusion:** a hook can paint real pixel art. This is what makes the catch banner
possible at all.

Also established: hooks **cannot** write to the TTY directly. `/dev/tty` from a hook
subprocess fails with `device not configured`, so `systemMessage` is the only route to
the screen. That is also why animation is out of reach for v1 — scrollback is immutable
and there is no cursor to move.

## 2. `systemMessage` costs zero model tokens

`systemMessage-zero-token-cost.log` records a deliberately large payload: 24,509 chars /
~6,127 tokens, containing a unique `CANARY7F3A` marker, delivered four times.

Measured across those four deliveries (~24.5k tokens of banner content):

```
             in  cache_create   cache_read
before        2           449       325786
after         2           449       325786
delta        +0            +0           +0
```

Structural confirmation, by transcript record type:

```
type=attachment   occurrences=430   <- the payload lives here (UI-only)
type=assistant    occurrences=1-5   <- only the marker string I typed myself
```

The 430-occurrence payload appears **only** in `attachment` records, never in a
model-visible `message[]`. Model context is assembled from `message[]`.

**Conclusion:** `systemMessage` is a UI channel, not a context channel. PokeClaude reads
token usage to drive catch odds and contributes nothing back. (`additionalContext` is the
field that *would* inject into context — deliberately unused here.)

## Reproducing

`render_test.py` is the surviving spike. Register it as a `PostToolUse` hook and trigger
any Bash call:

```json
{"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [
  {"type": "command", "command": "python3 /path/to/spike/render_test.py", "timeout": 5}
]}]}}
```
