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
| Cursor | verified | verified | partial | collapsed, strips colour — opens a PNG in the editor instead |
| Kiro IDE | verified | verified | partial | collapsed, strips colour — opens a PNG in the editor instead |
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


## Which host are we on?

`hosts.detect()` takes the first answer it gets, cheapest first:

1. `POKECLAUDE_HOST`, which always wins — detection cannot be perfect, and a user
   who says which host they are on should be believed.
2. Environment markers each host sets (`CODEX_HOME`, `CURSOR_TRACE_ID`,
   `KIRO_IDE`, `CLAUDECODE`, …). Most specific first: several hosts set
   CLAUDECODE-like variables for compatibility, so Claude Code is checked last.
3. `TERM_PROGRAM`.
4. The process tree.

Step 4 exists because of a case that broke everything above it. Cursor's **agent
panel** runs a tool with its environment scrubbed:

```
CURSOR_TRACE_ID unset   CLAUDECODE unset   TERM_PROGRAM unset   TERM=dumb
```

Nothing identifies the host, so detection fell through to the default — Claude
Code — which correctly refuses inline images because Claude Code cannot render
them. The Pokedex then printed ANSI art into the one panel that strips escapes:
the safe fallback silently disabled the feature it was protecting.

The parent chain still says what we are:

```
Python → zsh → Cursor Helper (Plugin): extension-host Agents Window → Cursor
```

So `ancestor_host()` walks it, matching process names against `PROCESS_MARKERS`.
Two properties matter:

- **Nearest match wins.** Claude Code running in Cursor's integrated terminal has
  both names in its chain and must resolve to Claude Code, or the inner agent's
  working truecolour art would be swapped for an image it renders perfectly well.
- **It is genuinely last.** It costs a `ps`, and the turn-end hook pays detection
  on every turn. Any environment marker short-circuits before the process table
  is read, which the tests assert by passing an ancestry callback that raises.

## Testing a host

Verify the hook works before waiting on a real catch:

```bash
python3 tools/check_host.py kiro          # probe one host
python3 tools/check_host.py kiro --show   # and print the banner
python3 tools/check_host.py cursor --open # really open the image card
python3 tools/check_host.py --all         # every host
python3 tools/check_host.py --explain     # what THIS process sees
```

`--explain` is the one to reach for when a host behaves differently from what the
table above promises. It probes nothing and launches nothing, so it is safe to
paste into any agent panel — which is the point, because the two facts that
decide everything can only be observed from inside the surface in question: what
the environment says we are, and whether stdout is a terminal. It prints both,
the process chain that launched us, and the mode they resolve to.

Run it in an agent's panel and in that same app's integrated terminal; the two
answers should differ, and if they do not, that is the bug.

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

## Images

Mono is a salvage operation: it gives up colour and half the resolution to survive
a channel that mangles both. Where a host can show an image instead, that is
strictly better, so the escape-stripping surface is bypassed rather than
accommodated.

There are two ways to get an image onto these surfaces, and they are not equal.

| Mode | How | Who |
|---|---|---|
| `inline` | the agent's reply contains `![](/abs/path.png)`, and the panel renders it | Cursor (sidebar + agents window), Kiro; the Codex app via `--inline on` |
| `tab` | the editor is told to open the file (`cursor -r`, `kiro -r`) | catches everywhere, since a hook cannot use `inline` |

### One adapter, two surfaces

`codex` is a single entry serving the Codex CLI and the Codex app, and they
disagree about exactly this. The app's panel renders a markdown image; the CLI is
a terminal that paints the escapes itself and would print a literal
`![pokedex](/…)` instead of art. Nothing in the environment tells them apart, and
the tty check does not help — both invoke us with a pipe.

So `codex` declares no capability and defaults to text, which is right for the
CLI and no worse than before for the app. An app user opts in once:

```bash
python3 plugin/scripts/config.py --inline on
```

This is the same shape as `mono`, which faced the identical split and resolved it
the same way. The `inline` config key overrides any host's declared answer in
both directions, so it also turns the channel on for Kiro if it turns out to work
there, or off for Cursor if a future version breaks it.

`inline` wins wherever it works: the art lands in the conversation, in colour,
with nothing to open, nothing to expand and no editor tab spent. It needs the
agent to echo one line, which is why only a **command** can use it — the
`/pokedex` skill instructs exactly that.

A **catch** cannot. The hook fires after the agent has stopped talking, so there
is nobody left to echo anything; catches take `tab`, which needs no cooperation.
That is the whole reason both modes exist.

`hosts.image_mode()` resolves which one applies. On a catch the hook writes the
whole banner — 64px sprite in full colour, name, types, rarity, Pokedex progress —
to a PNG. The text banner then carries the same facts with no art, so nothing is
shown twice.

### Never on a terminal

Both modes are suppressed when stdout is a tty. An integrated terminal inside
Kiro or Cursor is a real terminal — people run Claude Code and other agents in
one — and there the ANSI art renders perfectly. Replacing it with an image would
be a downgrade *and* a stolen tab. The panel gives us a pipe, the terminal gives
us a tty, and that is the whole test. `POKECLAUDE_IMAGE_TAB=1` overrides it for
anyone who wants an image from a terminal anyway.

### Two files, overwritten

`latest-catch.png` and `pokedex.png`, both in `~/.claude/pokeclaude/`, each
rewritten in place through a temp file and an atomic rename. Nothing accumulates:
the hundredth catch of a session costs the same ~10KB as the first, and a failed
write removes its own scratch file rather than leaving an orphan behind. The
stable names are also what make a `tab` redraw itself instead of stacking.

```bash
python3 plugin/scripts/config.py --image-tab on     # always
python3 plugin/scripts/config.py --image-tab off    # text banner only
python3 plugin/scripts/config.py --image-tab auto   # per agent (default)
```

Costs no tokens: the hook writes a file, the editor renders it. Encoding is
stdlib-only (`zlib`) and takes ~40ms for a ~10KB card, well inside the hook's
5-second timeout.

A host opts in by declaring a `viewer` in its `HOSTS` entry:

```python
"viewer": {"cli": "kiro", "app": "Kiro"},
```

`cli` is tried first (`kiro --reuse-window <path>`, the VS Code convention every
fork inherits) and `app` is the macOS fallback for when the shell command was
never installed — `open -g` so the editor does not steal focus. A host with
neither declares no viewer and falls back to mono.

Kiro and Cursor both declare one. The Codex app does not — it is standalone
Electron, not a VS Code fork, so there is no editor tab to open a PNG in. It
declares `markdown_images` instead and reaches the same result inline, which is
why a capability table beats a list of special cases.

### What is actually verified

Inline rendering was measured on the real apps: Cursor's sidebar, Cursor's agents
window and the Codex app all draw `![](/abs/path.png)` from an agent reply, with a
bare absolute path and no `file://` scheme. Public bug reports say otherwise and
are stale. Claude Code's desktop app does **not** — it renders truecolour art
inline already, so it needs neither mode. Kiro declares it too: its IDE is a VS Code
fork like Cursor and ships the same renderer family, so it takes the better
channel rather than waiting for a tab it does not need. `--inline off` reverts
it to the tab if that turns out to be wrong.

Cursor and Kiro declare the capability. The Codex app has it but shares its
adapter with a CLI that does not, so it is a setting there rather than a default.

The `tab` mode was read out of Cursor's own bundled `media-preview` extension
(1.0.0), not inferred from the VS Code lineage:

- PNG opens as an image, not as text. Its `customEditors` entry claims
  `*.{jpg,jpe,jpeg,png,bmp,gif,ico,webp,avif,svg}` at priority `builtin`, which
  makes the preview the default editor rather than an opt-in "reopen with".
- The preview reloads on change. It registers a `FileSystemWatcher` over the
  file's directory and, on a change matching its own resource, calls
  `updateBinarySize()` then `render()`. This is what makes the stable path
  (`~/.claude/pokeclaude/latest-catch.png`) work: one tab redraws itself for the
  whole session instead of a tab per catch. `onDidDelete` disposes the editor,
  so removing the file closes the tab cleanly too.

Kiro ships the same upstream extension, but Kiro is not installed here, so that
is inference rather than measurement. The remaining question on both is
subjective and cannot be answered from a terminal: whether a tab opening
mid-turn is welcome. `--image-tab off` if not.

`python3 tools/preview_card.py 25 --new` renders a card locally, and
`tools/check_host.py kiro` prints the exact command it would launch without
running it.

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
