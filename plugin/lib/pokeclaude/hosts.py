"""Host adapters: what each agent CLI gives us, and how to talk back to it.

PokeClaude's core is host-agnostic -- rolling, species selection, the Pokedex,
sprite rendering -- but two things are not, and they are exactly the two things a
catch needs:

  1. HOW MANY TOKENS the turn used. Every host stores this somewhere different,
     and some do not expose it at all.
  2. HOW TO SHOW the banner. Claude Code and Codex accept a `systemMessage` on
     stdout; Kiro and Copilot discard hook stdout entirely.

An adapter answers both for one host. Everything else is shared.

Verified behaviour per host (docs + local testing, not assumption):

  claude   Stop hook. `systemMessage` on stdout is rendered by the UI, preserving
           truecolour, newlines and half-blocks. Token counts come from the
           transcript JSONL at `transcript_path`.
  codex    `stop` hook (snake_case event names, unlike Claude). Also supports
           `systemMessage`, though the docs describe it as "surfaced as a warning
           in the UI or event stream" -- so it displays, but styling is the
           host's choice.
  cursor   `stop` hook. JSON over stdio, but `user_message` is documented only on
           deny paths (preToolUse and friends), so there is no guaranteed
           display channel on turn completion. Falls back to stderr.
  kiro     `Stop` hook. Docs are explicit that stdout is "ignored (others)" for
           non-context events, so a systemMessage cannot work. Falls back to
           stderr, which survives capture with escapes intact (measured).
  copilot  Hooks exist but the event list and output semantics are undocumented
           at the time of writing. Treated as the conservative case: stderr, and
           token counts absent.

The stderr fallback is deliberate and was measured rather than hoped for: a
subprocess whose stdout is captured still writes stderr as a separate stream, and
truecolour escapes plus newlines pass through unaltered. Whether a given host
then SHOWS that stream is the host's business -- which is why `display` is a
declared capability rather than a promise.
"""
import json
import os

# Where each host keeps things, and what it can do. Kept as data rather than
# subclasses: an adapter is a handful of facts, and a table makes the differences
# between hosts readable at a glance instead of scattered across methods.
HOSTS = {
    "claude": {
        "label": "Claude Code",
        "event": "Stop",
        "display": "systemMessage",
        "tokens": "transcript_jsonl",
        "config_dir": "~/.claude",
        "hooks_file": "hooks/hooks.json",
        # Explicitly False, not merely absent. Measured on the desktop app: a
        # markdown image in a reply does not render. Recorded so that `--inline
        # on` -- a global setting someone turns on for the Codex app -- cannot
        # reach across and replace working truecolour art here with a dead link.
        "markdown_images": False,
    },
    "codex": {
        # Event names are PascalCase, matching Claude Code -- confirmed against an
        # installed Codex plugin's hooks.json, not the lowercase form the prose
        # docs use.
        "label": "Codex",
        "event": "Stop",
        "display": "systemMessage",
        "tokens": "transcript_jsonl",
        "config_dir": "~/.codex",
        "hooks_file": "hooks.json",
        # NOT `markdown_images`, despite the Codex app rendering them (measured).
        # This one entry serves two surfaces: the app, whose panel eats escapes,
        # and the CLI, which paints truecolour perfectly. Declaring the capability
        # here would hand the CLI a markdown link to print into a terminal that
        # cannot render it -- trading working art for literal `![pokedex](...)`.
        # Nothing in the environment tells the two apart, so this follows the
        # precedent `mono` already set for exactly this split: the app's user
        # opts in once, with `config.py --inline on`.
    },
    "cursor": {
        "label": "Cursor",
        "event": "stop",
        "display": "stderr",
        "tokens": "payload",
        "config_dir": "~/.cursor",
        "hooks_file": "hooks.json",
        # Same story as Kiro, same fix: the agent panel collapses output and
        # strips escapes, but Cursor is a VS Code fork and its `cursor -r` opens
        # a PNG in a real image preview. Flag list confirmed against the
        # installed CLI, not assumed from the lineage.
        "viewer": {"cli": "cursor", "app": "Cursor"},
        # And its panel renders a markdown image in an agent reply, which beats
        # the tab -- measured in both the sidebar and the agents window, with a
        # bare absolute path. (Public bug reports say otherwise; they are stale.)
        "markdown_images": True,
    },
    "kiro": {
        # Colour support differs by surface, so it is NOT declared False here.
        # The Kiro CLI preserves truecolour and renders sprites correctly; only the
        # IDE's collapsed tool-call panel strips escapes, and there it also
        # collapses the output by default. Defaulting to mono for the whole host
        # would throw away the good rendering to accommodate the worse surface, so
        # colour is kept and POKECLAUDE_MONO=1 is the opt-in for the IDE.
        "label": "Kiro",
        "event": "Stop",
        "display": "stderr",
        "tokens": "payload",
        "config_dir": "~/.kiro",
        "hooks_file": "hooks/pokeclaude.json",
        # Kiro's IDE is a VS Code fork, so it already has an image viewer that
        # neither strips colour nor collapses anything. `viewer` says how to
        # reach it: the CLI first, falling back to the macOS app bundle, which
        # is there whether or not the user installed the shell command.
        "viewer": {"cli": "kiro", "app": "Kiro"},
        # Inline, like Cursor. Its IDE panel eats escapes and renders a
        # markdown image; the art arrives in the reply rather than as a tab.
        #
        # NOT gated on KIRO_IDE, though this entry serves the CLI as well and a
        # gate is what that split wants. The variable is simply not there:
        # measured inside a real Kiro IDE panel, KIRO_IDE and KIRO_WORKSPACE are
        # both unset while detection still resolves to kiro. Gating on it meant
        # the IDE -- the surface that needs images -- never got one.
        #
        # So the CLI's protection is the same as Cursor's: a person at a prompt
        # gets a tty and keeps their art, and anyone hitting this through a CLI
        # agent turns it off with `--inline off` or POKECLAUDE_INLINE=0. A
        # `gui_env` marker is still the right answer if one is ever found.
        "markdown_images": True,
    },
    "copilot": {
        "label": "GitHub Copilot CLI",
        "event": "stop",
        "display": "stderr",
        "tokens": "payload",
        "config_dir": "~/.copilot",
        "hooks_file": "hooks.json",
    },
}

DEFAULT_HOST = "claude"

# When a host exposes no token count at all, a turn still has to be worth
# something or the plugin simply never fires there. This is the assumed size of
# one turn on such hosts -- deliberately conservative (well under the measured
# 5,907-token median) so a host without instrumentation is unluckier than one
# with it, never luckier.
BLIND_TURN_TOKENS = 3000


# Process names that identify a host when the environment does not. Matched as
# substrings against the lowercased command of each ancestor, nearest first, so
# "Cursor Helper (Plugin): extension-host Agents Window" resolves to cursor.
PROCESS_MARKERS = (
    ("cursor", "cursor"),
    ("kiro", "kiro"),
    ("codex", "codex"),
    # The Codex app ships inside the ChatGPT desktop app, so that is the process
    # name its children see -- measured, not guessed. Without this the chain ends
    # in an unrecognised name and detection falls back to the default host.
    ("chatgpt", "codex"),
    ("claude", "claude"),
)


def _process_table():
    """{pid: (ppid, command)} for every process, from one `ps` call."""
    import subprocess

    out = subprocess.run(
        ["ps", "-Ao", "pid=,ppid=,comm="], capture_output=True, timeout=5
    ).stdout.decode("utf-8", "replace")
    table = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        try:
            table[int(parts[0])] = (int(parts[1]), parts[2] if len(parts) > 2 else "")
        except ValueError:
            continue
    return table


def ancestor_host(table=None, pid=None, limit=8):
    """Which host launched us, read off the process tree. None if unrecognised.

    The last resort, and the only signal left when a host scrubs its
    environment: Cursor's agent panel runs tools with no TERM_PROGRAM, no
    CURSOR_TRACE_ID and TERM=dumb, so every environment marker is absent and
    detection would otherwise fall through to the default. The parent chain still
    says `Cursor Helper (Plugin): extension-host Agents Window`.

    Deliberately last. It costs a subprocess, which a turn-end hook should not
    pay on every turn, and it is only reached when nothing cheaper answered.
    """
    try:
        table = table if table is not None else _process_table()
        pid = pid if pid is not None else os.getpid()
        for _ in range(limit):
            entry = table.get(pid)
            if entry is None:
                return None
            ppid, comm = entry
            lowered = comm.lower()
            for needle, host in PROCESS_MARKERS:
                if needle in lowered and host in HOSTS:
                    return host
            if ppid <= 1:
                return None
            pid = ppid
    except Exception:
        return None
    return None


def detect(env=None, ancestry=None):
    """Which host are we running under?

    Explicit configuration wins, because detection cannot be perfect and a user
    who says which host they are on should be believed. Otherwise fall back to
    environment markers each host sets, and finally to Claude Code -- the host
    this began as, and the only one where a wrong guess is harmless because its
    adapter is also the most capable.
    """
    env = env if env is not None else os.environ
    explicit = (env.get("POKECLAUDE_HOST") or "").strip().lower()
    if explicit in HOSTS:
        return explicit

    # Order matters: check the most specific markers first. Several hosts set
    # CLAUDECODE-like variables for compatibility, so a generic check would
    # misattribute them.
    for key, host in (
        ("CODEX_HOME", "codex"),
        ("CODEX_SANDBOX", "codex"),
        ("CURSOR_TRACE_ID", "cursor"),
        ("KIRO_IDE", "kiro"),
        ("KIRO_WORKSPACE", "kiro"),
        ("COPILOT_HOME", "copilot"),
        ("CLAUDE_PLUGIN_ROOT", "claude"),
        ("CLAUDECODE", "claude"),
    ):
        if env.get(key):
            return host

    term = (env.get("TERM_PROGRAM") or "").lower()
    if "kiro" in term:
        return "kiro"
    if "cursor" in term or "vscode" in term:
        return "cursor"

    # Nothing in the environment named a host. Before falling back to the
    # default, ask the process tree -- a panel that scrubs its environment is
    # precisely the case the default gets wrong, and getting it wrong there means
    # a catch is emitted on a channel that host ignores.
    found = (ancestry or ancestor_host)()
    if found in HOSTS:
        return found
    return DEFAULT_HOST


def spec(host=None):
    """The capability table for a host, defaulting to whatever we detect."""
    return HOSTS.get(host or detect(), HOSTS[DEFAULT_HOST])


def can_display(host=None):
    """Does this host have a channel that shows a banner to the user at all?"""
    return spec(host).get("display") in ("systemMessage", "stderr")


def has_colour(host=None):
    """Does this host preserve ANSI colour in the channel we use?

    Hosts default to True; only those measured to strip escapes declare
    `colour: False`. Callers use this to pick a density-ramp render instead, since
    a colour render on a colour-stripping host loses all its shape.
    """
    return spec(host).get("colour", True)


def use_mono(host=None, config=None):
    """Should art be drawn as shading silhouettes rather than colour?

    Resolved from, in order:
      1. POKECLAUDE_MONO env var (1/true forces on, 0/false forces off)
      2. the `mono` key in the user's config, which a GUI launched from the dock
         can still read even though it inherits no environment
      3. whether the detected host is known to strip colour

    The env var wins so a CLI on a mono-defaulted setup can opt back to colour for
    one run, and the config exists because it is the only channel that reaches an
    app started outside a shell -- the exact surface (Codex app, Kiro IDE, Cursor)
    that needs mono.
    """
    env = os.environ.get("POKECLAUDE_MONO")
    if env is not None:
        return env.strip().lower() not in ("", "0", "false", "no", "off")
    # A null value means "auto" -- treat it as unset, not as off, so it falls
    # through to the per-agent default rather than forcing colour everywhere.
    if config and config.get("mono") is not None:
        return bool(config["mono"])
    return not has_colour(host)


def viewer(host=None):
    """How to open an image file in this host's own UI, or None if it cannot."""
    return spec(host).get("viewer")


def renders_markdown_images(host=None, config=None):
    """Does this host's chat panel draw `![](/abs/path.png)` in an agent reply?

    Three-state per host, because there are genuinely three answers and collapsing
    them loses the one that matters:

      True     measured to render them (Cursor).
      False    measured NOT to (Claude Code, which paints truecolour art inline
               instead and would simply drop the link).
      absent   nobody has checked, or -- as with `codex` -- one adapter serves
               two surfaces that disagree, and nothing in the environment tells
               them apart.

    The `inline` setting decides the absent case, and may also switch OFF a host
    that declares True. What it must never do is switch ON a host declared False:
    the config is global across every agent, so `--inline on` for the Codex app
    would otherwise cost Claude Code its art entirely. A preference can override a
    measured possibility; it cannot override a measured impossibility.

    POKECLAUDE_INLINE beats both, and is the clean way out of the Codex split: the
    app is launched from the dock and sees no shell environment, so `--inline on`
    in the config reaches it, while `export POKECLAUDE_INLINE=0` in a shell
    profile reaches only the CLI.
    """
    env = os.environ.get("POKECLAUDE_INLINE")
    if env is not None:
        return env.strip().lower() not in ("", "0", "false", "no", "off")
    declared = spec(host).get("markdown_images")
    if declared is False:
        return False
    if config and config.get("inline") is not None:
        return bool(config["inline"])
    return bool(declared)


def is_gui(host=None):
    """Is this host's image-capable surface the one we are running under?

    Only meaningful for an adapter that serves both a GUI and a CLI. `gui_env`
    names the variable the GUI sets; without it the two are indistinguishable
    from in here, since a CLI agent hands its tools a pipe exactly like a panel
    does, and the CLI would get an editor window opening over the terminal art
    it renders perfectly well.

    No host declares one today. Kiro looked like the candidate -- KIRO_IDE is in
    the detection list -- but a real Kiro IDE panel reports it unset, so gating
    on it disabled images exactly where they were needed. Kept because the split
    is real and a measured marker would still be the right fix.
    """
    marker = spec(host).get("gui_env")
    return bool(os.environ.get(marker)) if marker else True


def is_terminal(stream):
    """Is this stream a real terminal, which will paint our escapes itself?

    The discriminator between the two ways these hosts run us. In an integrated
    terminal -- where someone may well be running a different agent entirely --
    stdout is a tty and the ANSI art works perfectly, so replacing it with an
    image would be a downgrade AND a stolen tab. From the agent panel stdout is a
    pipe, which is exactly the surface that eats the escapes.
    """
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def use_image(host=None, config=None, stream=None, agent=False):
    """Should art be delivered as a PNG here rather than as escapes?

    Precedence, highest first:
      1. POKECLAUDE_IMAGE_TAB -- an explicit answer, so it beats even the tty
         check; someone piping deliberately gets what they asked for.
      2. a tty on `stream`, when given: a terminal renders the art itself.
      3. the `image_tab` config key, which is the only channel that reaches a GUI
         launched from the dock with no shell environment.
      4. whether this host can show an image at all.

    Callers that can never be on a terminal (the turn-end hook) pass no stream.
    """
    env = os.environ.get("POKECLAUDE_IMAGE_TAB")
    if env is not None:
        return env.strip().lower() not in ("", "0", "false", "no", "off")
    # `agent` beats the tty check, and has to. Some panels run a tool through a
    # pty, so stdout is a terminal there in the technical sense while the surface
    # eating our escapes is a chat window -- the ChatGPT-hosted Codex app does
    # exactly this. A heuristic cannot separate those; the caller knows. Only a
    # skill file passes it, and a skill is agent-invoked by definition, so a
    # human running the same script by hand still gets the tty answer.
    # The env var is what the skills actually set. A FLAG breaks hard on any
    # older copy of the script -- "unrecognized arguments: --agent" and no
    # Pokedex at all -- and a skill cannot know which version it will resolve
    # to, since it globs plugin caches. An unknown variable is simply ignored.
    agent = agent or bool(os.environ.get("POKECLAUDE_AGENT"))
    if not agent and stream is not None and is_terminal(stream):
        return False
    if config and config.get("image_tab") is not None:
        return bool(config["image_tab"])
    # After the settings, so anyone who explicitly wants images in a CLI can
    # still have them, and before the capability check, so the default on a
    # split adapter is the surface-appropriate one.
    if not is_gui(host):
        return False
    return viewer(host) is not None or renders_markdown_images(host, config)


def image_mode(host=None, config=None, stream=None, agent=False):
    """How to deliver a PNG here: 'inline', 'tab', or None for text as usual.

    `inline` wins wherever it is available: the art lands in the conversation
    with nothing to open, nothing to expand and no tab spent. It needs the agent
    to echo a markdown link, though, so only a command can use it -- a turn-end
    hook fires after the agent has stopped talking and must take `tab`.
    """
    if not use_image(host, config, stream, agent):
        return None
    if renders_markdown_images(host, config):
        return "inline"
    return "tab" if viewer(host) else None


def emit(message, host=None, out=None, err=None):
    """Show `message` to the user through whatever channel this host offers.

    Returns the channel actually used, so a caller can record whether the catch
    was seen -- a host that cannot display one needs the Pokedex to surface it
    later instead.
    """
    import sys

    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    channel = spec(host).get("display")

    if channel == "systemMessage":
        # A single JSON object on stdout. suppressOutput keeps the host from ALSO
        # echoing the raw text, which would print the art twice -- once painted
        # and once with its escapes stripped.
        out.write(json.dumps({"systemMessage": message, "suppressOutput": True}))
        out.flush()
        return "systemMessage"

    if channel == "stderr":
        # Measured: stderr stays a separate stream when a host captures stdout,
        # and truecolour escapes and newlines survive intact. Whether the host
        # surfaces it is out of our hands, hence `seen` being recorded as
        # uncertain by the caller.
        err.write(message + "\n")
        err.flush()
        return "stderr"

    return None


def read_turn_tokens(payload, host=None):
    """Tokens the assistant produced this turn, and a marker identifying it.

    Returns (tokens, marker). The marker exists so the same turn is never gambled
    twice; when a host gives us nothing to key on, the caller falls back to the
    session id, which is coarser but still prevents a single turn being rolled
    repeatedly by a hook that fires more than once.
    """
    # Try a transcript whenever one is offered, regardless of what the host's
    # entry declares. `tokens` records the EXPECTED source, but a host that
    # happens to pass a transcript path should have it used -- real per-turn
    # counts always beat the blind fallback, and hosts change what they expose.
    path = payload.get("transcript_path") or payload.get("transcriptPath")
    if path:
        from . import transcript

        tokens, marker = transcript.read_turn_tokens(path)
        if marker is not None and tokens > 0:
            return tokens, marker

    # Hosts that pass usage inline. Field names vary, so try the plausible ones
    # rather than binding to one host's schema.
    for path in (
        ("usage", "output_tokens"),
        ("usage", "outputTokens"),
        ("tokens", "output"),
        ("output_tokens",),
        ("token_usage", "output_tokens"),
    ):
        node = payload
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, (int, float)) and node > 0:
            marker = (
                payload.get("turn_id")
                or payload.get("message_id")
                or payload.get("session_id")
            )
            return int(node), marker

    # No instrumentation at all: assume a modest turn so the host is playable,
    # keyed on whatever identifies this turn so it still cannot double-roll.
    marker = (
        payload.get("turn_id")
        or payload.get("message_id")
        or payload.get("conversation_id")
        or payload.get("session_id")
    )
    return (BLIND_TURN_TOKENS, marker) if marker else (0, None)
