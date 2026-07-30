#!/usr/bin/env python3
"""Render the Pokedex for the /pokeclaude:pokedex command.

Output reaches the screen in colour via the PostToolUse hook in
hooks/show.py, which re-emits this stdout as a systemMessage -- the only channel
that preserves truecolour escapes. Assistant reply text has its VT control
characters stripped, so the art must not be relayed there.

    pokedex.py                 first page of caught species
    pokedex.py --page 3        a specific page
    pokedex.py --all           include uncaught entries as dim silhouettes
    pokedex.py --id 25         detail view for one species (32px; --scale 1 for 64)
    pokedex.py --stats         summary only, no art
    pokedex.py --dupes         duplicate counts, most caught first
    pokedex.py --project       only what was caught in this project
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
        "--scale", type=int, default=3,
        help="sprite divisor: 1 = full 64px, 2 = 32px (detail default), "
             "3 = 21px (grid default)"
    )
    ap.add_argument(
        "--project",
        action="store_true",
        help="only Pokemon caught while working in this project",
    )
    ap.add_argument("--cwd", default=None, help="project directory (defaults to cwd)")
    ap.add_argument(
        "--dupes", action="store_true", help="list duplicate counts, most caught first"
    )
    args = ap.parse_args()
    # Distinguish "user chose a scale" from "default applied", because the grid
    # and the detail view want different defaults.
    args.scale_given = any(
        x == "--scale" or x.startswith("--scale=") for x in sys.argv[1:]
    )

    # Wrapping shreds pixel art, so the column count is derived from the real
    # terminal width rather than assumed. Hooks and pipes have no tty, hence the
    # explicit fallback chain.
    width = args.width or _term_width()

    meta = load_meta()
    roster = sorted(int(k) for k in meta)
    dexdata = store.load()

    if args.project:
        proj = store.project_key(args.cwd)
        caught, catches = store.project_view(dexdata, proj)
        scope = os.path.basename(proj) or proj
    else:
        proj = None
        caught = dexdata.get("caught", {})
        catches = dexdata.get("totals", {}).get("catches", 0)
        scope = None

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

        # A 64px sprite renders to 10-19KB because ~88% of the bytes are colour
        # escapes. That exceeds the size at which Claude Code persists tool
        # output to a file and shows only a 2KB preview -- which truncated the
        # art mid-sprite. 32px lands at 3.5-6KB and always survives intact.
        # --scale 1 still gives the full-resolution view for ctrl+o.
        detail_scale = args.scale if args.scale_given else 2
        if detail_scale > 1:
            from pokeclaude import sprite as spritelib

            blob = spritelib.downscale(blob, detail_scale)

        out += dex.render_detail(
            pid, blob, meta.get(str(pid)) or {}, caught.get(str(pid)), roster_ids=roster
        )
        print("\n".join(out))
        return 0

    # Header. Everything here is width-aware: the progress bar shrinks and the
    # catch total is dropped on narrow terminals, because a wrapped header looks
    # just as broken as wrapped pixel art.
    pct = 100.0 * unique / total if total else 0
    bar_w = max(8, min(32, width - 4))
    counts = "%d" % unique
    tail = "/%d caught  (%.0f%%)" % (total, pct)
    catch_txt = "   ·  %d total catches" % catches
    if 2 + len(counts) + len(tail) + len(catch_txt) > width:
        catch_txt = ""

    subtitle = "  ·  %s" % scope if scope else "  ·  pokeclaude"
    out.append("")
    out.append("  " + _c(GOLD, "POKEDEX", bold=True) + DIM + subtitle + RESET)
    out.append("  " + progress_bar(unique, total, width=bar_w))
    out.append(
        "  " + _c(GOLD, counts, bold=True) + DIM + tail + RESET + DIM + catch_txt + RESET
    )

    # Duplicates are worth surfacing: they are the visible sign of a long grind.
    dupes = sorted(
        ((int(k), v.get("count", 1)) for k, v in caught.items() if v.get("count", 1) > 1),
        key=lambda kv: (-kv[1], kv[0]),
    )
    if dupes and (args.stats or args.dupes):
        out.append("")
        out.append(DIM + "  duplicates" + RESET)
        for pid, n in dupes[: (None if args.dupes else 5)]:
            name = (meta.get(str(pid)) or {}).get("name", "?")
            out.append(
                "  "
                + _c(GOLD, "×%-3d" % n)
                + DIM
                + " #%03d %s" % (pid, name)
                + RESET
            )
        if not args.dupes and len(dupes) > 5:
            out.append(DIM + "  … and %d more (--dupes)" % (len(dupes) - 5) + RESET)
    elif args.dupes:
        out.append("")
        out.append(DIM + "  No duplicates yet." + RESET)
    out.append("")

    if args.stats or args.dupes:
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
    cell_w = 64 // scale
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
