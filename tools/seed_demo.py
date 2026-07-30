#!/usr/bin/env python3
"""Seed the throwaway demo Pokedex the README SVGs render from.

The demo collection used to live only in /tmp and was never committed, so the
exact state behind the screenshots (which species, which counts) could not be
reproduced. This script recreates it deterministically: run it, then run the
ansi_to_svg commands in tools/regen_readme.sh against the same POKECLAUDE_HOME.

    python3 tools/seed_demo.py --home /tmp/demodex
"""
import argparse
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "plugin", "lib"))

# The first grid page, in dex order. These are the twelve the README's grid
# image shows, so they must be the lowest-numbered caught species.
GRID = [1, 4, 7, 25, 39, 52, 54, 63, 68, 94, 104, 121]
DETAIL_LEGENDARY = 1007  # Koraidon, a caught legendary in the detail demo
DUPES = {25: 4, 52: 2, 94: 2}  # species -> total catches (Pikachu shows ×4)

# Header shows 8% of 1025 (~82 species) and 100 total catches. The grid only
# ever displays page one, so the rest are higher-numbered filler that never
# appears in the image but makes the progress bar and percentage realistic.
TARGET_SPECIES = 82
TARGET_CATCHES = 100
FILLER_START = 200  # higher than any grid entry, so page one is unchanged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", required=True)
    args = ap.parse_args()
    os.environ["POKECLAUDE_HOME"] = args.home

    import importlib

    from pokeclaude import store

    importlib.reload(store)
    if ".claude/pokeclaude" in store.ROOT:
        sys.exit("refusing to seed the real Pokedex")

    project = "/demo/project"

    def catch(pid, n=1):
        for _ in range(n):
            store.record_catch(pid, session_id="demo", project=project)

    # Page-one species, each caught its target number of times.
    for pid in GRID:
        catch(pid, DUPES.get(pid, 1))
    catch(DETAIL_LEGENDARY)  # a caught legendary for the detail demo

    # Fill up to the target species count with higher-numbered entries that
    # never reach page one, so the header percentage is realistic.
    seen = set(GRID) | {DETAIL_LEGENDARY}
    pid = FILLER_START
    while len(seen) < TARGET_SPECIES:
        if pid not in seen:
            catch(pid)
            seen.add(pid)
        pid += 1

    # Top up total catches (without new species) so the header count matches.
    d = store.load()
    while d["totals"]["catches"] < TARGET_CATCHES:
        catch(1)
        d = store.load()

    sys.stderr.write(
        "seeded %s: %d species, %d catches\n"
        % (args.home, len(d["caught"]), d["totals"]["catches"])
    )


if __name__ == "__main__":
    sys.exit(main())
