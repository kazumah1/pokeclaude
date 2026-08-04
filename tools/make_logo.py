#!/usr/bin/env python3
"""Generate the PokeClaude mark.

    python3 tools/make_logo.py                 docs/logo.png at 512px
    python3 tools/make_logo.py --size 128      a smaller one
    python3 tools/make_logo.py -o /tmp/x.png

Drawn rather than drawn-by-hand: the mark is defined by the maths below, so it
re-renders crisply at any size and there is no binary asset anybody has to edit.
Uses the plugin's own Canvas and PNG encoder, so it needs nothing installed.

The design is deliberately NOT a Poke Ball. That silhouette -- red over white,
split by a black equator, white button at the centre -- is Nintendo's trade
dress, and a plugin that ships pixel art of their creatures should not put their
mark on the tin as well. This keeps the *idea* of a capsule and takes none of
its execution: the palette is the project's own gold and charcoal, the band runs
diagonally instead of around the equator, and the catch is marked with the same
four-point sparkle the cards use for a shiny.
"""
import argparse
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "plugin", "lib"))

from pokeclaude import image  # noqa: E402

GRID = 32  # the mark is designed on a 32x32 pixel grid, then scaled up

TILE = (22, 23, 31)       # the card background, so the mark sits in the family
RIM = (12, 13, 18)        # outline, a shade under the tile
UPPER = (58, 65, 82)      # slate, lit from the top left
LOWER = (32, 37, 49)      # the shadowed half
BAND = (246, 200, 60)     # the project's gold
BUTTON = (255, 246, 208)  # cream, brighter than the band so it reads as a light
SHEEN = (86, 96, 118)     # a single highlight, top left


def pixel(x, y):
    """The colour of one grid cell, or None for the tile behind it."""
    # Work from the centre of each cell, so the circle is symmetric on an even
    # grid instead of leaning a pixel to one side.
    dx = x - (GRID - 1) / 2.0
    dy = y - (GRID - 1) / 2.0
    r = math.hypot(dx, dy)

    if r > 15.0:
        return None
    if r > 13.4:
        return RIM

    # The band runs corner to corner rather than around the equator. Distance to
    # the line y = -x, which is the diagonal through the centre.
    band = abs(dx + dy) / math.sqrt(2)

    # The button sits on that diagonal at the centre.
    if r < 3.0:
        return BUTTON
    if r < 4.6:
        return BAND
    if band < 2.2:
        return BAND
    if band < 3.0:
        return RIM

    # Which side of the diagonal we are on decides the shading, so the lighting
    # agrees with the band instead of cutting across it.
    if dx + dy < 0:
        # A highlight arc hugging the upper-left edge. Bounded by ANGLE, not by
        # the signs of dx and dy: a quadrant test gives a blocky wedge with a
        # corner in it, where an arc reads as a curved surface catching light.
        theta = math.atan2(dy, dx)
        if 11.1 < r < 12.9 and -2.85 < theta < -1.75:
            return SHEEN
        return UPPER
    return LOWER


def render(size):
    scale = max(1, size // GRID)
    canvas = image.Canvas(GRID * scale, GRID * scale, TILE)
    for y in range(GRID):
        for x in range(GRID):
            colour = pixel(x, y)
            if colour is not None:
                canvas.rect(x * scale, y * scale, scale, scale, colour)
    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=512,
                    help="output edge in pixels, rounded down to a multiple of 32")
    ap.add_argument("-o", "--out", default=os.path.join(REPO, "docs", "logo.png"))
    args = ap.parse_args()

    canvas = render(args.size)
    d = os.path.dirname(args.out)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(args.out, "wb") as f:
        f.write(canvas.to_png())
    print("%s  %dx%d  (%d bytes)"
          % (args.out, canvas.w, canvas.h, os.path.getsize(args.out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
