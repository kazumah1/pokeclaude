#!/usr/bin/env python3
"""Render the Pokedex for the /pokedex command.

Unlike the catch banner, this output is printed directly rather than passed
through a hook field, so it has no length ceiling and no schema to satisfy.

    pokedex.py                 first page of caught species
    pokedex.py --page 3        a specific page
    pokedex.py --all           include uncaught entries as dim silhouettes
    pokedex.py --id 25         detail view for one species
    pokedex.py --stats         summary only, no art
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
ASSETS = os.path.join(HERE, "..", "assets")
SPRITES = os.path.join(ASSETS, "sprites")
META = os.path.join(ASSETS, "pokemon.json")

from pokeclaude import dex, store  # noqa: E402

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
GOLD = (246, 200, 60)


def _c(rgb, text, bold=False):
    return "%s\033[38;2;%d;%d;%dm%s%s" % (
        BOLD if bold else "", rgb[0], rgb[1], rgb[2], text, RESET
    )


def _term_width(default=80):
    """Terminal width, falling back sanely when there is no tty (pipes, hooks)."""
    env = os.environ.get("POKECLAUDE_WIDTH") or os.environ.get("COLUMNS")
    if env and env.isdigit():
        return int(env)
    try:
        import shutil

        w = shutil.get_terminal_size((default, 24)).columns
        return w if w and w > 20 else default
    except Exception:
        return default


def load_meta():
    try:
        with open(META) as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return {}


def progress_bar(unique, total, width=32):
    filled = int(round(width * unique / float(total))) if total else 0
    return (
        _c(GOLD, "█" * filled) + DIM + "░" * (width - filled) + RESET
    )


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--per-page", type=int, default=None)
    ap.add_argument("--cols", type=int, default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--id", type=int, default=None)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--width", type=int, default=None, help="override terminal width")
    ap.add_argument(
        "--scale", type=int, default=2, help="1 = full 32px sprites, 2 = 16px grid"
    )
    args = ap.parse_args()

    # Wrapping shreds pixel art, so the column count is derived from the real
    # terminal width rather than assumed. Hooks and pipes have no tty, hence the
    # explicit fallback chain.
    width = args.width or _term_width()

    meta = load_meta()
    roster = sorted(int(k) for k in meta)
    dexdata = store.load()
    caught = dexdata.get("caught", {})
    unique = len(caught)
    total = len(roster)

    out = []

    if args.id is not None:
        pid = args.id
        blob = None
        try:
            with open(os.path.join(SPRITES, "%d.json" % pid)) as f:
                blob = json.load(f)
        except (IOError, OSError, ValueError):
            pass
        if blob is None:
            print("No sprite for #%d" % pid)
            return 1
        out += dex.render_detail(pid, blob, meta.get(str(pid)) or {}, caught.get(str(pid)))
        print("\n".join(out))
        return 0

    # Header. Everything here is width-aware: the progress bar shrinks and the
    # catch total is dropped on narrow terminals, because a wrapped header looks
    # just as broken as wrapped pixel art.
    pct = 100.0 * unique / total if total else 0
    bar_w = max(8, min(32, width - 4))
    counts = "%d" % unique
    tail = "/%d caught  (%.0f%%)" % (total, pct)
    catches = "   ·  %d total catches" % dexdata.get("totals", {}).get("catches", 0)
    if 2 + len(counts) + len(tail) + len(catches) > width:
        catches = ""

    out.append("")
    out.append("  " + _c(GOLD, "POKEDEX", bold=True) + DIM + "  ·  pokeclaude" + RESET)
    out.append("  " + progress_bar(unique, total, width=bar_w))
    out.append(
        "  " + _c(GOLD, counts, bold=True) + DIM + tail + RESET + DIM + catches + RESET
    )
    out.append("")

    if args.stats:
        print("\n".join(out))
        return 0

    if unique == 0 and not args.all:
        out.append(DIM + "  No Pokemon caught yet." + RESET)
        out.append(
            DIM + "  Keep working — they appear as you use Claude Code." + RESET
        )
        out.append("")
        print("\n".join(out))
        return 0

    ids = roster if args.all else sorted(int(k) for k in caught)

    scale = max(1, args.scale)
    cell_w = 32 // scale
    cols = args.cols or dex.fit_columns(width, cell_w)
    per = max(1, args.per_page or cols * 3)  # three rows per page by default

    pages = max(1, (len(ids) + per - 1) // per)
    page = min(max(1, args.page), pages)
    chunk = ids[(page - 1) * per : page * per]

    entries = [(pid, caught.get(str(pid))) for pid in chunk]
    out += dex.render_grid(
        entries,
        SPRITES,
        meta,
        cols=cols,
        show_uncaught=args.all,
        scale=scale,
    )

    out.append(
        DIM
        + "  page %d/%d" % (page, pages)
        + ("   ·  --page %d for more" % (page + 1) if page < pages else "")
        + RESET
    )
    out.append("")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
