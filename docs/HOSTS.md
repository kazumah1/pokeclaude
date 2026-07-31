# Agent adapters

PokeClaude's core is agent-agnostic. An adapter is the small amount of configuration
one agent needs to call the same hooks, plus two facts: where the turn's token count
lives, and how a hook can show the user something.

## What is actually verified

Each row is what has been observed on the real agent, not what the docs promise.

| Agent | Install | Hook fires | Banner seen | Notes |
|---|---|---|---|---|
| Claude Code | verified | verified | verified | full colour inline |
| Codex CLI | verified | verified | verified | live catch + `/pokedex`, full colour |
| Kiro CLI | verified | verified | verified | full colour |
| Codex app | verified | verified | partial | collapsed, strips colour — set `--mono on` |
| Cursor | verified | verified | partial | collapsed, strips colour — set `--mono on` |
| Kiro IDE | verified | verified | partial | collapsed, strips colour — set `--mono on` |
| Copilot CLI | not tested | not tested | not tested | hook events undocumented |

`python3 tools/check_host.py <agent>` runs the real hook with a synthetic turn and
reports which channel the banner came out on. It proves the plugin side works; it
cannot prove the agent invokes the hook, which is what "hook fires" above means.

## Install routes

| Agent | Route | Event |
|---|---|---|
| Claude Code | `claude plugin marketplace add` | `Stop` |
| Codex CLI | `codex plugin marketplace add` | `Stop` |
| Cursor | `install.py --host cursor` | `stop` |
| Kiro | `install.py --host kiro` | `Stop` |
| Copilot CLI | `install.py --host copilot` | `stop` |

Claude Code and Codex both read `.claude-plugin/marketplace.json` and treat `plugin/`
as the plugin root, so one manifest serves both. The hook command uses
`${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT}}` because they set different variables for the
same thing.

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


## Testing a host

Verify the hook works before waiting on a real catch:

```bash
python3 tools/check_host.py kiro          # probe one host
python3 tools/check_host.py kiro --show   # and print the banner
python3 tools/check_host.py --all         # every host
```

This runs the real hook with a synthetic large turn, so it forces a catch rather
than depending on luck, and uses a throwaway Pokedex so your collection is
untouched. It reports which channel the banner came out on and whether colour and
pixel art survived.

If that passes but no catch ever shows up in the host itself, the problem is the
host's hook wiring or how it handles that channel — not PokeClaude.

### Kiro specifics

Kiro documents hooks at **workspace** level (`.kiro/hooks/`). A user-level
`~/.kiro/hooks/` is neither documented nor ruled out, so install both if unsure:

```bash
python3 install.py --host kiro --workspace /path/to/project
python3 install.py --host kiro
```

Kiro's docs say a command hook's stdout is "ignored" for `Stop`, and that stderr
goes to the agent on exit 2. PokeClaude exits 0 and writes the banner to stderr,
so whether Kiro surfaces it is untested — check the Agent Hooks panel in the Kiro
UI to confirm the hook is registered and firing. Catches are recorded either way,
and `pokedex.py` announces any you did not see.

## Mono (colour-free) art

CLIs preserve truecolour and render sprites correctly. The GUI surfaces — the Codex
app, the Cursor agent panel, the Kiro IDE — strip escapes, which turns a render into
a flat field of identical blocks, and collapse the output so it has to be expanded.

No agent defaults to mono, since that would sacrifice the CLI's good rendering for the
GUI's worse one. Turn it on for a GUI:

```bash
python3 plugin/scripts/config.py --mono on     # solid silhouettes
python3 plugin/scripts/config.py --mono off    # force colour
python3 plugin/scripts/config.py --mono auto    # decide per agent (default)
```

This is stored in the config rather than an env var, because a GUI launched from the
dock inherits no shell environment. `POKECLAUDE_MONO=1` still works for a one-off in a
CLI, and overrides the config.

The art is a solid silhouette at full resolution. Shading ramps (`░▒▓█`) were tried
first and are worse — those are dither patterns in most fonts, so at one glyph per
pixel they render as static rather than tones.

### Slash commands in chat

Kiro reads Agent Skills (`SKILL.md` bundles) and exposes them as slash commands
when you type `/` in chat. `install.py --host kiro` copies the bundles from
`skills/` into `~/.kiro/skills/`, giving you:

| Command | Does |
|---|---|
| `/pokedex` | browse the collection (takes the same flags as the script) |
| `/pokeclaude` | show or change the catch rate |
| `/pokeclaude-release` | release a Pokemon, or all of them |

The name in each `SKILL.md` frontmatter must match its folder name, lowercase with
hyphens only — Kiro rejects mismatches.

Skills locate the repo themselves by probing `$POKECLAUDE_ROOT`, the working
directory, and a few common clone paths, because a skill invoked from a chat
sidebar gets no plugin-root variable. Set `POKECLAUDE_ROOT` if your clone lives
somewhere unusual.
