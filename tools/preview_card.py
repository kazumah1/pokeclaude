#!/usr/bin/env python3
"""Render a catch card to a PNG without waiting for a catch, or for a host.

    python3 tools/preview_card.py 25                 normal Pikachu
    python3 tools/preview_card.py 25 --shiny --new   the full-gold version
    python3 tools/preview_card.py 384 -o /tmp/x.png  somewhere specific

This exists because the card's whole point is a host that cannot be tested from
a terminal: on Kiro the image lands in an editor tab, so the only way to check
the layout while writing it is to make one and open it yourself.
"""
import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "plugin", "lib"))

ASSETS = os.path.join(REPO, "plugin", "assets")

from pokeclaude import card, sprite as spritelib  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("species", type=int, help="national dex number")
    ap.add_argument("-o", "--out", default=None, help="output path")
    ap.add_argument("--shiny", action="store_true")
    ap.add_argument("--new", action="store_true", help="show it as a first catch")
    ap.add_argument("--dupes", type=int, default=3, help="count when not --new")
    args = ap.parse_args()

    with open(os.path.join(ASSETS, "pokemon.json")) as f:
        meta = json.load(f)
    roster = sorted(int(k) for k in meta)

    blob = spritelib.load(os.path.join(ASSETS, "sprites"), args.species,
                          shiny=args.shiny)
    if blob is None:
        print("no sprite for #%d" % args.species)
        return 1

    info = meta.get(str(args.species)) or {}
    out = args.out or os.path.join(
        REPO, "card-%03d%s.png" % (args.species, "-shiny" if args.shiny else "")
    )
    card.write(
        out,
        blob=blob,
        name=info.get("name", "pokemon"),
        dex_id=args.species,
        type_names=info.get("types") or [],
        is_new=args.new,
        dup_count=args.dupes,
        unique=137,
        roster_size=len(roster),
        roster_ids=roster,
        shiny=args.shiny,
    )
    print("%s  (%d bytes)" % (out, os.path.getsize(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
