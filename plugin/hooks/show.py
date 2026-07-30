#!/usr/bin/env python3
"""PostToolUse hook: render pokeclaude script output in real colour.

Why this exists. Sprite art only survives to the screen through channels Claude
Code paints itself. A hook's `systemMessage` is one (verified: newlines,
truecolour SGR and half-blocks all arrive intact). Text the assistant writes into
its reply is NOT -- that is content, and it gets its VT control characters
stripped, which is why relayed pokedex output arrives as monochrome blocks while
the catch banner is fully coloured.

So when the /pokedex or /release scripts run, this hook takes their
stdout and re-emits it as a systemMessage. Same bytes, correct channel. It also
sets suppressOutput so the raw copy is hidden and the art is not shown twice.
"""
import json
import os
import sys

MARKERS = ("pokedex.py", "release.py")
# A systemMessage is a single UI string; a very long one would flood the view, and
# the pokedex is paginated precisely so it does not need to.
MAX_CHARS = 60_000


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0

    if os.environ.get("POKECLAUDE_DISABLE"):
        return 0

    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command") or ""
    if not any(m in command for m in MARKERS):
        return 0
    # Only claim output from this plugin's own scripts, never any command that
    # merely mentions them (a grep, an edit, a git diff).
    if "pokeclaude" not in command:
        return 0

    resp = payload.get("tool_response")
    if isinstance(resp, dict):
        out = resp.get("stdout") or resp.get("output") or ""
    elif isinstance(resp, str):
        out = resp
    else:
        out = ""

    out = out.rstrip("\n")
    if not out or "\x1b[" not in out:
        # Nothing to rescue: no art means no reason to duplicate the output.
        return 0
    if len(out) > MAX_CHARS:
        return 0
    # When output is large, Claude Code replaces it with a persisted-file wrapper
    # containing only a short preview. Re-emitting that would print a sprite
    # truncated mid-render, which looks worse than not rendering at all. The
    # scripts are sized to stay under the threshold, so this is a backstop.
    if "<persisted-output>" in out or "Output too large" in out:
        return 0

    print(json.dumps({"systemMessage": out, "suppressOutput": True}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never disturb the session
