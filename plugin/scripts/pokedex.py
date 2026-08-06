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
    pokedex.py --stats         summary with rarity breakdown, no art
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


def _deliver(canvas, mode, host, header, note=""):
    """Emit a view as an image. True if the art was delivered that way.

    Two channels, decided by the host rather than here. `inline` writes the PNG
    and prints the markdown link for the agent to echo, which puts the art in the
    conversation itself -- no tab, nothing to expand. `tab` opens it in the
    editor, for hosts that mangle the escapes but do not render markdown images.

    False means nothing was shown and the caller must fall back to ANSI art.
    """
    from pokeclaude import card

    path = None
    if mode == "inline":
        path = card.write_inline(canvas, card.FILENAME_DEX, host=host)
    elif mode == "tab":
        path = card.show_canvas(canvas, card.FILENAME_DEX, host=host)
    if not path:
        return False

    print("\n".join(header))
    print("")
    if mode == "inline":
        # The agent has to repeat this line for it to render: a tool result is
        # shown as terminal output, and only the reply itself goes through the
        # markdown renderer. Stated as an instruction because that is what the
        # skill files point at.
        print("![pokedex](%s)" % path)
        print("")
        print("  ^ Reply with exactly that line and nothing else. It renders the")
        print("    Pokedex inline. Do not describe or summarise the image.")
    else:
        print("  Opened in an editor tab: %s" % path)
    if note:
        print("")
        print(note)
    return True


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


def rarity_breakdown(caught, roster):
    """Unique species owned per rarity tier, against roster totals.

    Returns lines ready to append: a dim 'rarity' header plus one row per tier
    in encounter.TIERS order (MYTHICAL → COMMON). Mythical and legendary labels
    are gold to match the detail/banner treatment; rare and common stay dim.
    """
    from pokeclaude import encounter

    owned = {label: 0 for _, label in encounter.TIERS}
    totals = {label: 0 for _, label in encounter.TIERS}
    for pid in roster:
        totals[encounter.rarity_tier(pid)] += 1
    for key in caught:
        owned[encounter.rarity_tier(int(key))] += 1

    lines = ["", DIM + "  rarity" + RESET]
    for _, label in encounter.TIERS:
        n, t = owned[label], totals[label]
        # Skip tiers the roster does not use — RARE is defined but currently
        # empty (weights jump from legendary ≤0.12 straight to common 1.0).
        if t == 0:
            continue
        if label in ("MYTHICAL", "LEGENDARY"):
            name = _c(GOLD, "%-9s" % label, bold=True)
        else:
            name = DIM + "%-9s" % label + RESET
        lines.append("  " + name + DIM + " %d/%d" % (n, t) + RESET)
    return lines


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
        "--scale", type=int, default=4,
        help="sprite divisor: 1 = full 64px, 2 = 32px (detail default), "
             "3 = 21px, 4 = 16px (grid default)"
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
    ap.add_argument(
        "--no-image", action="store_true",
        help="never render as a PNG; force the ANSI art even on a host that would "
             "otherwise show an image",
    )
    ap.add_argument(
        "--agent", action="store_true",
        help="an agent invoked this, not a person at a shell prompt. Skips the "
             "tty check: some panels run tools through a pty, so stdout looks "
             "like a terminal while the surface strips escapes. Skill files pass "
             "it; typing the command yourself does not.",
    )
    ap.add_argument(
        "--image", action="store_true",
        help="always render as a PNG and print its path, even from a terminal. "
             "The way to see what an agent panel would get without being in one.",
    )
    args = ap.parse_args()

    from pokeclaude import hosts as _hosts

    config = store.load_config()
    host = _hosts.detect()

    # --mono forces silhouettes; otherwise use_mono resolves env var, then the
    # `mono` config key, then whether the agent strips colour. One resolver so the
    # pokedex and the catch banner never disagree.
    if not args.mono:
        args.mono = _hosts.use_mono(host, config)

    # Whether to draw a PNG instead, and how to deliver it. `stream` is what keeps
    # this off a terminal: someone running another agent in the IDE's integrated
    # terminal gets a tty, real colour, and none of this.
    mode = None if args.no_image else _hosts.image_mode(
        host, config, sys.stdout, agent=args.agent
    )
    if args.image and not args.no_image:
        # Forced. Falls back to `inline`, which writes the file and prints its
        # path without launching anything -- the safe thing to do on a host that
        # has no viewer, and enough to inspect the render by hand.
        mode = mode or "inline"
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

        # An image view is built from the FULL 64px sprite, before the downscale
        # below: the size cap that forces one is a limit on text, and this is not
        # text.
        if mode:
            from pokeclaude import card

            entry = caught.get(str(pid))
            n = (entry or {}).get("count", 0)
            head = "  " + _c(GOLD, "POKEDEX", bold=True) + DIM + "  ·  entry #%03d %s%s" % (
                pid,
                (meta.get(str(pid)) or {}).get("name", "?"),
                "  ×%d" % n if n > 1 else "",
            ) + RESET
            if _deliver(
                card.detail(
                    pid, blob, meta.get(str(pid)) or {}, entry,
                    roster_ids=roster, showing_shiny=want_shiny,
                ),
                mode, host, [head],
            ):
                return 0

        # A 64px sprite renders to 10-33KB because ~88% of the bytes are colour
        # escapes. Claude Code separately persists any hook systemMessage over
        # ~10,000 characters to a file on disk and logs a truncated duplicate in
        # the transcript underneath the (still fully rendered) art -- there is no
        # flag to keep the content but skip that side effect. Checked across the
        # full roster: --scale 1 crosses that line for 1001 of 1025 species, so
        # it does this almost every time, not just for unlucky species. Clamping
        # it to 32px was tried and reverted -- losing the resolution bump was
        # worse than the saved-file tradeoff, so --scale 1 is opt-in as-is:
        # accept the persisted file and duplicate preview for real 64px detail.
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

    # Rarity breakdown is summary-only: the grid already has the sprites, and
    # stuffing four extra lines into every page would push art off-screen.
    if args.stats or args.dupes:
        out.extend(rarity_breakdown(caught, roster))

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
    # Fixed page budget, independent of terminal width. Tying this to cols (e.g.
    # "three rows" = cols * 3) let a wide terminal fit more columns and thus MORE
    # sprites per page. The binding constraint isn't the ~30KB Bash output limit
    # (raising per-page count alone still fits under that) -- it's that the
    # PostToolUse hook re-emits this same text as a `systemMessage`, and hook
    # output strings are hard-capped at 10,000 characters with no override
    # (unlike BASH_MAX_OUTPUT_LENGTH). Past that, Claude Code saves it to a file
    # and shows only a preview, which is the truncation this page must never
    # trigger. 4 entries at scale 4 measures 6.5-8KB even in adversarial cases
    # (max dupes, all-shiny, the largest sprites in the roster) -- comfortably
    # under 10,000 at any terminal width, since page size no longer depends on
    # cols.
    #
    # None of that binds an image. A PNG has no character cap at all, so a page
    # there is sized by what reads well on screen instead -- 24 entries, six to a
    # row, which is six times what the text grid can carry.
    if mode:
        per = max(1, args.per_page or 24)
        img_cols = max(1, args.cols or 6)
    else:
        per = max(1, args.per_page or 4)

    pages = max(1, (len(ids) + per - 1) // per)
    page = min(max(1, args.page), pages)
    chunk = ids[(page - 1) * per : page * per]

    entries = [(pid, caught.get(str(pid))) for pid in chunk]

    if mode:
        from pokeclaude import card

        pct = (100.0 * unique / total) if total else 0.0
        head = "  " + _c(GOLD, "POKEDEX", bold=True) + DIM + "  %d/%d (%.0f%%)   page %d/%d" % (
            unique, total, pct, page, pages
        ) + RESET
        note = DIM + "  --page %d for more" % (page + 1) + RESET if page < pages else ""
        if _deliver(
            card.grid(
                entries, SPRITES, meta, cols=img_cols, show_uncaught=args.all,
                title=[("POKEDEX  %d/%d (%.0f%%)" % (unique, total, pct), (246, 200, 60))],
                footer=[("PAGE %d/%d" % (page, pages), (124, 128, 145))],
            ),
            mode, host, [head], note,
        ):
            return 0

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
