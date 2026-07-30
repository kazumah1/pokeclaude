#!/usr/bin/env python3
"""Convert a script's real ANSI output into an SVG for the README.

GitHub strips ANSI escapes from fenced code blocks, so a README cannot show the
plugin's actual colours inline -- the best a code block manages is a monochrome
approximation that looks nothing like the terminal. Images are the only way, and
generating them from the scripts' own stdout means the README can never drift
from what the code really prints.

SVG rather than PNG: it is text, so it diffs and compresses well in git, needs no
image library, and stays crisp at any zoom. Each cell becomes a <rect> for the
background plus a <text> for the glyph.

    python3 tools/ansi_to_svg.py --demo catch --out docs/catch.svg
    python3 tools/ansi_to_svg.py --cmd "scripts/pokedex.py --id 143" --out x.svg
"""
import argparse
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "plugin", "lib"))

SGR = re.compile(r"\x1b\[([0-9;]*)m")

# Cell metrics, deliberately terminal-faithful rather than idealised.
#
# A character cell is CW wide and holds two square pixels (PH each) stacked, plus
# a LINE_GAP strip below that shows the canvas through. That gap is the real thing
# a terminal produces: half-block art draws two pixels per character row (top via
# the glyph, bottom via the cell background), and the terminal's line-height
# leaves a hairline of its own background between character rows -- the faint
# horizontal seams you see every second pixel row. An earlier version overlapped
# the rects to erase those seams, which made the README look cleaner than any real
# terminal ever does. This reproduces them instead.
CW = 9.0
PH = 9.0  # pixel height; square against CW
# The seam is the terminal's line-height gap between character rows, and it is a
# hairline, not a bar -- roughly a tenth of a pixel row. Drawn as the canvas
# colour, so it reads as a faint dark line across coloured sprite regions (the
# real artifact) and is invisible against the matching dark background, exactly
# as in a terminal.
LINE_GAP = 1.0
CH = PH * 2 + LINE_GAP  # full character-cell height
FONT_SIZE = 15
BASELINE = 13.7  # glyph baseline within the 2*PH text area

# Glyphs the sprite renderer uses as pixels rather than text. These become
# coloured rects; everything else (labels, progress bar, symbols) stays text.
UPPER, LOWER, FULL = "▀", "▄", "█"
PIXEL_GLYPHS = (UPPER, LOWER, FULL, " ")

# Terminal defaults, tuned to read like a dark terminal rather than pure black.
DEFAULT_FG = (220, 223, 228)
DEFAULT_BG = (13, 17, 23)  # GitHub dark canvas, so the image blends into the page

DIM_FACTOR = 0.55


def parse(text):
    """Turn ANSI text into a grid of (char, fg, bg, bold) cells."""
    rows = []
    fg, bg, bold, dim = None, None, False, False

    for line in text.split("\n"):
        cells = []
        i = 0
        while i < len(line):
            m = SGR.match(line, i)
            if m:
                for part in _split_codes(m.group(1)):
                    if part == "reset":
                        fg, bg, bold, dim = None, None, False, False
                    elif part == "bold":
                        bold = True
                    elif part == "dim":
                        dim = True
                    elif part == "bgdefault":
                        bg = None
                    elif isinstance(part, tuple):
                        which, rgb = part
                        if which == "fg":
                            fg = rgb
                        else:
                            bg = rgb
                i = m.end()
                continue
            cells.append((line[i], fg, bg, bold, dim))
            i += 1
        rows.append(cells)
    return rows


def _split_codes(body):
    """Yield semantic tokens from one SGR body.

    The renderer merges a simultaneous foreground and background change into a
    single sequence ("38;2;r;g;b;48;2;r;g;b") to halve the escape count, so this
    has to consume truecolour triples positionally rather than splitting on ';'
    and treating each number independently.
    """
    if body in ("", "0"):
        return ["reset"]
    parts = body.split(";")
    out, i = [], 0
    while i < len(parts):
        p = parts[i]
        if p == "1":
            out.append("bold")
            i += 1
        elif p == "2":
            out.append("dim")
            i += 1
        elif p == "0":
            out.append("reset")
            i += 1
        elif p == "49":
            out.append("bgdefault")
            i += 1
        elif p in ("38", "48") and i + 4 < len(parts) and parts[i + 1] == "2":
            rgb = (int(parts[i + 2]), int(parts[i + 3]), int(parts[i + 4]))
            out.append(("fg" if p == "38" else "bg", rgb))
            i += 5
        else:
            i += 1
    return out


def _hex(rgb):
    return "#%02x%02x%02x" % rgb


def _dimmed(rgb):
    return tuple(int(round(c * DIM_FACTOR)) for c in rgb)


def _pixel_colours(cell):
    """(top, bottom) pixel colour for a half-block cell, or None where empty.

    Mirrors the sprite renderer: fg paints the glyph's solid half, bg the other.
      ▀ solid top    -> top=fg,  bottom=bg
      ▄ solid bottom -> top=bg,  bottom=fg
      █ solid both   -> top=fg,  bottom=fg
      space          -> both bg (usually transparent)
    A None colour means "let the canvas show through", i.e. a transparent pixel.
    """
    ch, fg, bg, _bold, _dim = cell
    if ch == UPPER:
        return fg, bg
    if ch == LOWER:
        return bg, fg
    if ch == FULL:
        return fg, fg
    return bg, bg  # space


def to_svg(rows, pad=14):
    width = max((len(r) for r in rows), default=0)
    w = width * CW + pad * 2
    h = len(rows) * CH + pad * 2

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%.0f" height="%.0f" '
        'viewBox="0 0 %.1f %.1f" font-family="ui-monospace,SFMono-Regular,'
        'Menlo,Consolas,monospace" font-size="%d">'
        % (w, h, w, h, FONT_SIZE),
        '<rect width="100%%" height="100%%" fill="%s" rx="6"/>' % _hex(DEFAULT_BG),
    ]

    # A row is "pixel art" if every non-space cell is a half/full block. Those
    # rows are drawn as two rows of square pixel rects with the terminal's
    # line-gap left showing between character rows. Text rows (labels, progress
    # bar) are drawn as glyphs, exactly as a terminal would.
    def is_pixel_row(cells):
        return any(c[0] in (UPPER, LOWER, FULL) for c in cells) and all(
            c[0] in PIXEL_GLYPHS for c in cells
        )

    for y, cells in enumerate(rows):
        y0 = pad + y * CH
        if is_pixel_row(cells):
            # Two pixel bands per character row; the LINE_GAP below them stays the
            # canvas colour, which is the seam a real terminal shows.
            for band, get in ((0, lambda p: p[0]), (1, lambda p: p[1])):
                by = y0 + band * PH
                run_col, run_start = None, 0
                for x in range(len(cells) + 1):
                    col = get(_pixel_colours(cells[x])) if x < len(cells) else None
                    if col != run_col:
                        if run_col is not None:
                            parts.append(
                                '<rect x="%g" y="%g" width="%g" height="%g" '
                                'fill="%s"/>'
                                % (pad + run_start * CW, by,
                                   (x - run_start) * CW, PH, _hex(run_col))
                            )
                        run_col, run_start = col, x
            continue

        # Text row: backgrounds first (rare here), then glyph runs.
        run_bg, run_start = None, 0
        for x in range(len(cells) + 1):
            bg = cells[x][2] if x < len(cells) else None
            if bg != run_bg:
                if run_bg is not None:
                    parts.append(
                        '<rect x="%g" y="%g" width="%g" height="%g" fill="%s"/>'
                        % (pad + run_start * CW, y0,
                           (x - run_start) * CW, CH, _hex(run_bg))
                    )
                run_bg, run_start = bg, x

        x = 0
        while x < len(cells):
            ch, fg, bg, bold, dim = cells[x]
            if ch == " ":
                x += 1
                continue
            run = [ch]
            j = x + 1
            while j < len(cells):
                c2, f2, b2, bo2, d2 = cells[j]
                if c2 == " ":
                    k = j
                    while k < len(cells) and cells[k][0] == " ":
                        k += 1
                    if k >= len(cells) or (cells[k][1], cells[k][3], cells[k][4]) != (
                        fg, bold, dim
                    ):
                        break
                    run.extend(" " * (k - j))
                    j = k
                    continue
                if (f2, bo2, d2) != (fg, bold, dim):
                    break
                run.append(c2)
                j += 1
            colour = fg or DEFAULT_FG
            if dim:
                colour = _dimmed(colour)
            text = "".join(run)
            parts.append(
                '<text x="%g" y="%g" fill="%s"%s textLength="%g" '
                'lengthAdjust="spacing" xml:space="preserve">%s</text>'
                % (pad + x * CW, y0 + BASELINE, _hex(colour),
                   ' font-weight="bold"' if bold else "",
                   len(text) * CW, _escape(text))
            )
            x = j if j > x else x + 1

    parts.append("</svg>")
    return "\n".join(parts)


def _escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def demo_catch(pid, width=80):
    """Render a catch banner exactly as the hook would emit it."""
    import json

    from pokeclaude import banner

    meta = json.load(open(os.path.join(REPO, "plugin", "assets", "pokemon.json")))
    roster = sorted(int(k) for k in meta)
    blob = json.load(
        open(os.path.join(REPO, "plugin", "assets", "sprites", "%d.json" % pid))
    )
    info = meta[str(pid)]
    return banner.compose(
        blob, info["name"], pid, info["types"], True, 1, 1, len(roster),
        width=width, roster_ids=roster,
    )


def run_script(cmd, width, home=None):
    env = dict(os.environ)
    env["POKECLAUDE_WIDTH"] = str(width)
    # A demo collection lives in its own POKECLAUDE_HOME so generating README
    # images never reads, writes or depends on the author's real Pokedex.
    if home:
        env["POKECLAUDE_HOME"] = home
    argv = [sys.executable] + cmd.split()
    argv[1] = os.path.join(REPO, "plugin", argv[1])
    p = subprocess.run(argv, capture_output=True, env=env)
    if p.returncode != 0:
        sys.exit("command failed: %s" % p.stderr.decode()[:400])
    return p.stdout.decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", choices=["catch"], default=None)
    ap.add_argument("--id", type=int, default=143)
    ap.add_argument("--cmd", default=None, help="script path + args, relative to plugin/")
    ap.add_argument("--width", type=int, default=80)
    ap.add_argument("--home", default=None, help="POKECLAUDE_HOME for a demo collection")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.demo == "catch":
        text = demo_catch(args.id, args.width)
    elif args.cmd:
        text = run_script(args.cmd, args.width, args.home)
    else:
        text = sys.stdin.read()

    text = text.strip("\n")
    svg = to_svg(parse(text))
    out = os.path.join(REPO, args.out) if not os.path.isabs(args.out) else args.out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(svg)
    sys.stderr.write(
        "wrote %s (%.1f KB, %d rows)\n" % (args.out, len(svg) / 1024.0,
                                           len(text.split("\n")))
    )


if __name__ == "__main__":
    sys.exit(main())
