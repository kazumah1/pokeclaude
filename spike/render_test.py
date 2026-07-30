#!/usr/bin/env python3
"""Spike: does a hook's systemMessage preserve newlines, ANSI truecolor, and
Unicode half-blocks when Claude Code renders it?

Emits a small pokeball sprite via half-block rendering plus probe lines for
256-colour, truecolour, and wide-char handling. Logs what it emitted so we can
diff "what the hook sent" against "what the user saw".
"""
import json
import os
import sys

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spike.log")

# 8x8 pokeball. R=red, W=white, K=black, .=transparent
SPRITE = [
    "..RRRR..",
    ".RRRRRR.",
    "RRRRRRRR",
    "RRRKKRRR",
    "WWWKKWWW",
    "WWWWWWWW",
    ".WWWWWW.",
    "..WWWW..",
]
PALETTE = {
    "R": (237, 28, 36),
    "W": (245, 245, 245),
    "K": (30, 30, 30),
}


def halfblock(rows):
    """Two pixel rows per terminal row: fg = upper pixel, bg = lower pixel."""
    out = []
    for y in range(0, len(rows), 2):
        top, bot = rows[y], rows[y + 1]
        line = ""
        for x in range(len(top)):
            t, b = PALETTE.get(top[x]), PALETTE.get(bot[x])
            if t is None and b is None:
                line += " "
            elif t is None:
                line += "\033[38;2;%d;%d;%dm\033[49m▄\033[0m" % b
            elif b is None:
                line += "\033[38;2;%d;%d;%dm\033[49m▀\033[0m" % t
            else:
                line += "\033[38;2;%d;%d;%dm\033[48;2;%d;%d;%dm▀\033[0m" % (t + b)
        out.append(line)
    return out


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}

    parts = [
        "── POKECLAUDE SPIKE ──",
        "1 plain ascii: A wild MISSINGNO appeared!",
        "2 truecolor:   \033[38;2;237;28;36mRED\033[0m \033[38;2;60;200;90mGREEN\033[0m \033[38;2;70;130;255mBLUE\033[0m",
        "3 256color:    \033[38;5;196mRED\033[0m \033[38;5;46mGREEN\033[0m \033[38;5;33mBLUE\033[0m",
        "4 bold/dim:    \033[1mBOLD\033[0m \033[2mDIM\033[0m \033[3mITALIC\033[0m",
        "5 halfblocks (no color): ▀▄▀▄█",
        "6 sprite below:",
    ]
    parts.extend("   " + r for r in halfblock(SPRITE))
    parts.append("7 emoji/wide:  ⚡ ✨ CJK完")
    parts.append("── END SPIKE ──")

    msg = "\n".join(parts)

    with open(LOG, "w") as f:
        f.write("hook fired\n")
        f.write("event=%s\n" % payload.get("hook_event_name"))
        f.write("tool=%s\n" % payload.get("tool_name"))
        f.write("payload_keys=%s\n" % sorted(payload.keys()))
        f.write("msg_lines=%d msg_chars=%d\n" % (len(parts), len(msg)))
        f.write("--- RAW BYTES OF systemMessage ---\n")
        f.write(repr(msg) + "\n")

    print(json.dumps({"systemMessage": msg}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
