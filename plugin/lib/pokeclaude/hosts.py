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
    },
    "codex": {
        # Event names are PascalCase, matching Claude Code -- confirmed against an
        # installed Codex plugin's hooks.json, not the lowercase form the prose
        # docs use.
        "label": "Codex CLI",
        "event": "Stop",
        "display": "systemMessage",
        "tokens": "transcript_jsonl",
        "config_dir": "~/.codex",
        "hooks_file": "hooks.json",
    },
    "cursor": {
        "label": "Cursor",
        "event": "stop",
        "display": "stderr",
        "tokens": "payload",
        "config_dir": "~/.cursor",
        "hooks_file": "hooks.json",
    },
    "kiro": {
        "label": "Kiro",
        "event": "Stop",
        "display": "stderr",
        "tokens": "payload",
        "config_dir": "~/.kiro",
        "hooks_file": "hooks/pokeclaude.json",
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


def detect(env=None):
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
    return DEFAULT_HOST


def spec(host=None):
    """The capability table for a host, defaulting to whatever we detect."""
    return HOSTS.get(host or detect(), HOSTS[DEFAULT_HOST])


def can_display(host=None):
    """Does this host have a channel that shows a banner to the user at all?"""
    return spec(host).get("display") in ("systemMessage", "stderr")


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
