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

# Cell metrics. 9 x 18 is close to a real terminal's aspect at 15px monospace,
# which matters because half-block art assumes cells are about twice as tall as
# they are wide -- get this wrong and every sprite looks stretched.
#
# Both are integers on purpose. With fractional metrics the background rects land
# on sub-pixel boundaries and antialiasing leaves a faint horizontal seam between
# every row of sprite art, which is very visible across a large flat-coloured
# area.
CW, CH = 9.0, 18.0
FONT_SIZE = 15
BASELINE = 13.7  # glyph baseline within the cell

# Half-unit overlap on background rects, to kill inter-row seams. See to_svg().
BLEED = 0.5

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

    # Backgrounds first, merged into runs. One rect per cell would triple the
    # file for art that is mostly flat colour horizontally.
    for y, cells in enumerate(rows):
        run_bg, run_start = None, 0
        for x in range(len(cells) + 1):
            bg = cells[x][2] if x < len(cells) else None
            if bg != run_bg:
                if run_bg is not None:
                    # Bleed each rect half a unit past its cell on all sides.
                    #
                    # Exact tiling is NOT enough. Abutting rects share an edge,
                    # and whenever the image is scaled to a non-integer device
                    # ratio that edge lands mid-pixel: the rasteriser blends both
                    # neighbours with whatever is under them, leaving a faint
                    # line across every row of flat-coloured sprite. Overlapping
                    # removes the shared edge entirely. Same-coloured neighbours
                    # overlap invisibly; different-coloured ones differ by half a
                    # unit at a boundary that is one sprite pixel wide anyway.
                    parts.append(
                        '<rect x="%g" y="%g" width="%g" height="%g" fill="%s"/>'
                        % (pad + run_start * CW - BLEED, pad + y * CH - BLEED,
                           (x - run_start) * CW + BLEED * 2, CH + BLEED * 2,
                           _hex(run_bg))
                    )
                run_bg, run_start = bg, x

    # Then glyphs, grouped into runs of identical style.
    #
    # Interior spaces are KEPT inside a run rather than skipped. Skipping them
    # and restarting the next run at its own x would be pixel-identical for a
    # monospace font in theory, but it silently drops the gap when a run is
    # emitted as one <text>: "…pokedex to browse" rendered as "…pokedexto
    # browse". Only leading spaces are skipped, to avoid emitting empty elements.
    for y, cells in enumerate(rows):
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
                # A space continues the run only if more same-styled text
                # follows it; a trailing space would just pad the element.
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
            # textLength pins the run to the exact grid width.
            #
            # Without it the layout is a lie: cells are positioned on a CW grid
            # but the glyphs advance at whatever width the viewer's monospace
            # font happens to use. Any font wider than CW pushes long runs past
            # the declared viewport and the text is clipped mid-word -- the right
            # edge of a wide grid, or "…to browse" losing its last letters.
            # lengthAdjust=spacing stretches the gaps rather than the letterforms,
            # so glyphs keep their shape.
            parts.append(
                '<text x="%g" y="%g" fill="%s"%s textLength="%g" '
                'lengthAdjust="spacing" xml:space="preserve">%s</text>'
                % (pad + x * CW, pad + y * CH + BASELINE, _hex(colour),
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
