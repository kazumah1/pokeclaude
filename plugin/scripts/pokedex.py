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
SHINY = (255, 236, 140)  # brighter than GOLD so the shiny tally stands apart


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


def _shiny_chance():
    """The configured shiny rate, for display. Imported lazily to keep startup light."""
    from pokeclaude import encounter

    return encounter.SHINY_CHANCE


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
    ap.add_argument(
        "--shiny",
        action="store_true",
        help="show only the shinies you have caught",
    )
    ap.add_argument(
        "--normal",
        action="store_true",
        help="with --id, show the ordinary colours of a species you own a shiny of",
    )
    ap.add_argument(
        "--mono",
        action="store_true",
        help="render with shading glyphs instead of colour, for hosts that strip "
             "ANSI escapes (auto-enabled on those hosts)",
    )
    args = ap.parse_args()

    # --mono forces silhouettes; otherwise use_mono resolves env var, then the
    # `mono` config key, then whether the agent strips colour. One resolver so the
    # pokedex and the catch banner never disagree.
    if not args.mono:
        from pokeclaude import hosts as _hosts

        args.mono = _hosts.use_mono(config=store.load_config())
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
        from pokeclaude import sprite as spritelib

        # Shiny colours are EARNED, never previewed: showing them for a species you
        # have not caught shiny would spend the reward before it is won. So the art
        # follows ownership, and --normal is the way back to the ordinary colours
        # for a species you own both of.
        entry = caught.get(str(pid))
        owns_shiny = bool(entry and entry.get("shiny"))
        want_shiny = owns_shiny and not args.normal
        blob = spritelib.load(SPRITES, pid, shiny=want_shiny)
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
            pid,
            blob,
            meta.get(str(pid)) or {},
            caught.get(str(pid)),
            roster_ids=roster,
            showing_shiny=want_shiny,
            mono=args.mono,
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
    if args.shiny:
        subtitle += "  ·  shinies only"
    out.append("")
    out.append("  " + _c(GOLD, "POKEDEX", bold=True) + DIM + subtitle + RESET)
    out.append("  " + progress_bar(unique, total, width=bar_w))
    out.append(
        "  " + _c(GOLD, counts, bold=True) + DIM + tail + RESET + DIM + catch_txt + RESET
    )

    # Catches made on hosts that cannot display a banner are announced here, once.
    # Skipped for --stats/--dupes so a summary view never silently consumes them.
    if not (args.stats or args.dupes or args.project):
        pending = store.take_unseen()
        if pending:
            names = []
            for key in pending[:6]:
                nm = (meta.get(str(key)) or {}).get("name", "#%s" % key)
                names.append(nm)
            more = "" if len(pending) <= 6 else " and %d more" % (len(pending) - 6)
            out.append(
                "  "
                + _c(GOLD, "NEW", bold=True)
                + DIM
                + " while you were working: %s%s" % (", ".join(names), more)
                + RESET
            )

    # Shiny tally, only once there is one to report -- an unconditional "0 shinies"
    # would advertise an absence on every single run.
    n_shiny = sum(e.get("shiny", 0) for e in caught.values())
    if n_shiny:
        species = sum(1 for e in caught.values() if e.get("shiny"))
        out.append(
            "  "
            + _c(SHINY, "✧", bold=True)
            + DIM
            + " %d shiny catch%s across %d species"
            % (n_shiny, "" if n_shiny == 1 else "es", species)
            + RESET
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

    if args.shiny:
        # A shiny showcase: only species you hold a shiny of. --all is ignored
        # here, since "every uncaught species, as a shiny" is not a thing you own.
        ids = sorted(int(k) for k, v in caught.items() if v.get("shiny"))
        if not ids:
            out.append(DIM + "  No shinies yet." + RESET)
            out.append(
                DIM + "  Every catch has a 1 in %d chance of being shiny."
                % int(round(1.0 / _shiny_chance())) + RESET
            )
            out.append("")
            print("\n".join(out))
            return 0
    elif args.all:
        ids = roster
    else:
        ids = sorted(int(k) for k in caught)

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
        mono=args.mono,
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
