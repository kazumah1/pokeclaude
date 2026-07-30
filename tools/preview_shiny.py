#!/usr/bin/env python3
"""Preview any species' normal and shiny art side by side, in the terminal.

A developer/curiosity tool. The plugin itself never shows you a shiny you have not
caught, so this is the way to look at the art without spoiling your own Pokedex --
it reads the baked sprites directly and touches no collection data.

    python3 tools/preview_shiny.py 25            # pikachu, both variants
    python3 tools/preview_shiny.py pikachu       # by name
    python3 tools/preview_shiny.py 6 149 384     # several at once
    python3 tools/preview_shiny.py --scale 2 25  # larger
    python3 tools/preview_shiny.py --random 5    # five random species
"""
import argparse
import json
import os
import random
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "plugin", "lib"))

from pokeclaude import sprite as spritelib  # noqa: E402

ASSETS = os.path.join(REPO, "plugin", "assets")
SPRITES = os.path.join(ASSETS, "sprites")

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
SHINY = (255, 236, 140)


def _c(rgb, text, bold=False):
    return "%s\033[38;2;%d;%d;%dm%s%s" % (
        BOLD if bold else "", rgb[0], rgb[1], rgb[2], text, RESET
    )


def load_meta():
    with open(os.path.join(ASSETS, "pokemon.json")) as f:
        return json.load(f)


def resolve(token, meta):
    """Accept a dex number or a name."""
    token = str(token).strip().lower()
    if token.isdigit():
        return int(token) if token in meta or str(int(token)) in meta else None
    for key, info in meta.items():
        if info.get("name", "").lower() == token:
            return int(key)
    # tolerate a prefix, so "chariz" finds charizard
    hits = [int(k) for k, v in meta.items() if v.get("name", "").startswith(token)]
    return sorted(hits)[0] if hits else None


def side_by_side(left, right, gap=4):
    """Join two blocks of rendered art column-wise."""
    import re

    ansi = re.compile(r"\x1b\[[0-9;]*m")
    lw = max([len(ansi.sub("", r)) for r in left] or [0])
    height = max(len(left), len(right))
    out = []
    for i in range(height):
        a = left[i] if i < len(left) else ""
        b = right[i] if i < len(right) else ""
        pad = " " * max(0, lw - len(ansi.sub("", a)))
        out.append((a + pad + " " * gap + b).rstrip())
    return out


def show(pid, meta, scale):
    info = meta.get(str(pid)) or {}
    name = (info.get("name") or "?").upper()

    normal = spritelib.load(SPRITES, pid, shiny=False)
    shiny = spritelib.load(SPRITES, pid, shiny=True)
    if normal is None:
        print("  no sprite for #%d" % pid)
        return
    if scale > 1:
        normal = spritelib.downscale(normal, scale)
        shiny = spritelib.downscale(shiny, scale) if shiny else None

    identical = shiny is not None and shiny["pal"] == normal["pal"]

    print()
    print(
        "  #%03d %s   %s%s"
        % (
            pid,
            _c((246, 200, 60), name, bold=True),
            DIM + ", ".join(t.upper() for t in (info.get("types") or [])) + RESET,
            DIM + "   (shiny art is identical upstream)" + RESET if identical else "",
        )
    )
    import re

    left = spritelib.render(normal, indent=2)
    right = spritelib.render(shiny, indent=2) if shiny else ["  (no shiny art)"]

    # Caption each column over its own sprite.
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    lw = max([len(ansi.sub("", r)) for r in left] or [0])
    print(
        "  " + DIM + "normal" + RESET + " " * max(0, lw - 6) + "   "
        + _c(SHINY, "✧ shiny", bold=True)
    )
    for line in side_by_side(left, right):
        print(line)


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("species", nargs="*", help="dex numbers or names")
    ap.add_argument(
        "--scale", type=int, default=3,
        help="sprite divisor: 1 = full 64px, 2 = 32px, 3 = 21px (default)",
    )
    ap.add_argument("--random", type=int, default=0, help="show N random species")
    args = ap.parse_args()

    meta = load_meta()
    roster = sorted(int(k) for k in meta)

    ids = []
    for token in args.species:
        pid = resolve(token, meta)
        if pid is None:
            sys.stderr.write("unknown species: %s\n" % token)
            continue
        ids.append(pid)
    if args.random:
        ids += random.sample(roster, min(args.random, len(roster)))
    if not ids:
        ids = [25]  # pikachu, the recognisable default

    for pid in ids:
        show(pid, meta, max(1, args.scale))
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
