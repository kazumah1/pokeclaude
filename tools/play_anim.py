#!/usr/bin/env python3
"""Play a catch animation in the terminal, in place, via cursor repaint.

This is what the GIFs in docs/ would look like moving in a real terminal. It is
a manual demo, NOT how the plugin behaves: the actual catch banner is emitted
once through a hook `systemMessage` to immutable scrollback, and a hook cannot
reach /dev/tty to repaint. So the plugin can never animate a catch. Running this
script yourself can, because it owns the TTY -- it prints a frame, moves the
cursor back up over it, and prints the next.

    python3 tools/play_anim.py --style reveal  --id 143
    python3 tools/play_anim.py --style bob     --id 25   --loops 6
    python3 tools/play_anim.py --style sparkle --id 150

Run it in a real terminal. Piped or captured (including via Claude Code's `!`),
the cursor moves collapse and you just see the final frame -- that is the same
reason the plugin cannot animate, shown from the other side.
"""
import argparse
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))

import animate_demo as ad  # noqa: E402

HIDE, SHOW = "\033[?25l", "\033[?25h"
CLEAR_LINE = "\033[2K"


def _vis_height(frame):
    return frame.count("\n") + 1


def play(frames, delay_ms, loops, out=sys.stdout):
    """Repaint `frames` in place `loops` times, leaving the last frame drawn.

    All frames are padded to a common height so a shorter frame cannot leave
    stale rows from the previous one on screen.
    """
    height = max(_vis_height(f) for f in frames)
    padded = []
    for f in frames:
        lines = f.split("\n")
        lines += [""] * (height - len(lines))
        padded.append(lines)

    delay = delay_ms / 1000.0
    interactive = out.isatty()
    if interactive:
        out.write(HIDE)
    try:
        first = True
        for _ in range(loops):
            for lines in padded:
                if not first:
                    # Move the cursor back to the top of the block. Without a
                    # TTY this escape is inert and frames stack instead, which is
                    # exactly why the plugin's hook output cannot animate.
                    out.write("\033[%dA" % height)
                body = "\n".join(CLEAR_LINE + ln for ln in lines)
                out.write("\r" + body + "\n")
                out.flush()
                first = False
                time.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        if interactive:
            out.write(SHOW)
            out.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--style", choices=sorted(ad.STYLES), default="reveal")
    ap.add_argument("--id", type=int, default=143)
    ap.add_argument("--loops", type=int, default=4)
    args = ap.parse_args()

    frames, delay = ad.STYLES[args.style](args.id)
    # The reveal reads best played once and then held; loop the idle/sparkle.
    loops = 1 if args.style == "reveal" else args.loops
    play(frames, delay, loops)
    return 0


if __name__ == "__main__":
    sys.exit(main())
