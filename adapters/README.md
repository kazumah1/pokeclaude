# Host adapters

PokeClaude's core is host-agnostic. Each adapter here is the small amount of
configuration one agent CLI needs to call the same two hooks.

| Host | Config file | Event | Banner shown via |
|---|---|---|---|
| Claude Code | `~/.claude/settings.json` (or plugin) | `Stop` | `systemMessage` |
| Codex CLI | `~/.codex/hooks.json` | `stop` | `systemMessage` |
| Cursor | `~/.cursor/hooks.json` | `stop` | stderr |
| Kiro | `.kiro/hooks/pokeclaude.json` | `Stop` | stderr |
| Copilot CLI | `~/.copilot/hooks.json` | `stop` | stderr |

Run `python3 install.py` from the repo root to detect installed hosts and wire
them up. `python3 install.py --host kiro` targets one explicitly, and
`--dry-run` prints what would change without writing.

## Where the banner appears

Claude Code and Codex render a hook's `systemMessage`, so a catch appears inline
with full colour.

The other hosts discard hook stdout. The banner goes to **stderr** instead, which
survives with colours intact — whether it is displayed depends on the host. On any
host where it is not shown, the catch is still recorded and flagged, and
`/pokedex` announces it the next time you open your collection, so nothing is
lost.

## Token counts

Claude Code and Codex write a JSONL transcript and pass its path to the hook, so
the roll uses the turn's real `output_tokens`.

Hosts that pass usage inline are read from the hook payload. Where a host exposes
no token data at all, each turn counts as a flat 3,000 tokens — under the measured
median, so an uninstrumented host is slightly unluckier rather than luckier.

## Adding a host

Add an entry to `HOSTS` in `plugin/lib/pokeclaude/hosts.py`:

```python
"myhost": {
    "label": "My Host",
    "event": "stop",              # its turn-end hook name
    "display": "stderr",          # or "systemMessage"
    "tokens": "payload",          # or "transcript_jsonl"
    "config_dir": "~/.myhost",
    "hooks_file": "hooks.json",
},
```

Then add a template in `adapters/<myhost>/` and a detection marker in
`hosts.detect()`. No other code changes are needed.
