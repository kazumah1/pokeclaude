#!/usr/bin/env python3
"""Release Pokemon from the Pokedex — the destructive counterpart to /pokedex.

This deletes collection data, so nothing happens without an explicit
`--confirm`. Without it the script reports exactly what *would* be removed and
exits non-zero, which also makes it safe for the model to run first to show the
user the consequences before asking.

    release.py pikachu              dry run: what releasing Pikachu would do
    release.py pikachu --confirm    actually release it
    release.py all --confirm        clear the whole Pokedex
    release.py all --project --confirm   clear only this project's records
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
META = os.path.join(HERE, "..", "assets", "pokemon.json")

from pokeclaude import store  # noqa: E402

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
GOLD = (246, 200, 60)
RED = (220, 90, 80)


def _c(rgb, text, bold=False):
    return "%s\033[38;2;%d;%d;%dm%s%s" % (
        BOLD if bold else "", rgb[0], rgb[1], rgb[2], text, RESET
    )


def load_meta():
    try:
        with open(META) as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return {}


def resolve(target, meta):
    """Map a user-supplied name or dex number to a species id."""
    t = str(target).strip().lower()
    if t.isdigit():
        return int(t) if str(int(t)) in meta else None
    for k, v in meta.items():
        if (v.get("name") or "").lower() == t:
            return int(k)
    return None


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("target", help='species name, dex number, or "all"')
    ap.add_argument("--confirm", action="store_true", help="actually perform the release")
    ap.add_argument(
        "--project",
        action="store_true",
        help="only clear this project's records, leaving the global Pokedex intact",
    )
    ap.add_argument("--cwd", default=None, help="project directory (defaults to cwd)")
    args = ap.parse_args()

    meta = load_meta()
    proj = store.project_key(args.cwd) if args.project else None
    dex = store.load()

    if args.project:
        entries, _catches = store.project_view(dex, proj)
        scope_label = "project %s" % os.path.basename(proj)
    else:
        entries = dex.get("caught") or {}
        scope_label = "your Pokedex"

    releasing_all = str(args.target).strip().lower() == "all"

    if releasing_all:
        species = sorted(int(k) for k in entries)
        total = sum(
            (v.get("count", 1) if isinstance(v, dict) else v) for v in entries.values()
        )
        if not species:
            print(DIM + "Nothing to release — %s is already empty." % scope_label + RESET)
            return 0
        what = "%s (%d species, %d catches)" % (
            _c(RED, "EVERYTHING", bold=True),
            len(species),
            total,
        )
        target_id = None
    else:
        target_id = resolve(args.target, meta)
        if target_id is None:
            print("Unknown Pokemon: %r" % args.target)
            print(DIM + 'Use a name ("pikachu"), a dex number (25), or "all".' + RESET)
            return 1
        key = str(target_id)
        if key not in entries:
            name = (meta.get(key) or {}).get("name", "#%d" % target_id)
            print(
                DIM
                + "%s is not in %s — nothing to release." % (name.title(), scope_label)
                + RESET
            )
            return 0
        e = entries[key]
        count = e.get("count", 1) if isinstance(e, dict) else e
        name = (meta.get(key) or {}).get("name", "#%d" % target_id)
        what = "%s %s" % (
            _c(GOLD, name.title(), bold=True),
            DIM + ("(×%d)" % count if count > 1 else "") + RESET,
        )

    if not args.confirm:
        print("")
        print("  Would release %s from %s." % (what, scope_label))
        print(
            DIM
            + "  This cannot be undone. Re-run with --confirm to proceed."
            + RESET
        )
        print("")
        return 2  # non-zero: nothing was changed

    result = store.release(species_id=target_id, project=proj)
    if result is None:
        print(
            DIM
            + "Could not acquire the Pokedex lock — nothing was changed. Try again."
            + RESET
        )
        return 1

    print("")
    if result["species"] == 0:
        print(DIM + "  Nothing was released." + RESET)
    elif releasing_all:
        print(
            "  Released %s — %d species, %d catches cleared from %s."
            % (_c(RED, "everything", bold=True), result["species"], result["catches"], scope_label)
        )
    else:
        key = str(target_id)
        name = (meta.get(key) or {}).get("name", "#%d" % target_id)
        print(
            "  %s was released from %s. %s"
            % (_c(GOLD, name.title(), bold=True), scope_label,
               DIM + "Farewell." + RESET)
        )
    remaining = store.load()
    if args.project:
        ent, _ = store.project_view(remaining, proj)
        print(DIM + "  %d species remain in this project." % len(ent) + RESET)
    else:
        print(
            DIM
            + "  %d species remain in your Pokedex." % len(remaining.get("caught") or {})
            + RESET
        )
    print("")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
