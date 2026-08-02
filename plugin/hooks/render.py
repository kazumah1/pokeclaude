#!/usr/bin/env python3
"""PostToolUse(Bash): re-emit the casino frame in real color.

Truecolor pixel art only survives to the screen through channels Claude Code
paints itself; a hook's systemMessage is one. When a casino.py command runs,
read the frame it wrote and emit it as a systemMessage. Never disturb a session.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

# Real frames run large: the biggest legitimate one is a 5-opponent hold'em
# showdown (~292K chars). The cap only guards against a runaway/corrupt dump.
MAX_CHARS = 400_000


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    command = (payload.get("tool_input") or {}).get("command") or ""
    if "casino.py" not in command:
        return 0
    from casino import store
    try:
        with open(store.frame_path()) as f:
            frame = f.read().rstrip("\n")
    except (IOError, OSError):
        return 0
    if not frame or "\x1b[" not in frame or len(frame) > MAX_CHARS:
        return 0
    print(json.dumps({"systemMessage": frame}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # never disturb the session
