"""Pokedex rendering: paginated sprite grid plus single-entry detail view.

This is the safest visual surface in the plugin. Its output is printed by the
assistant rather than squeezed through a hook field, so there is no schema, no
length ceiling and no truncation to design around -- full-size sprites and long
grids are fine here.

Sprites are laid out in a grid whose column count is derived from the available
terminal width, and each cell's caption sits under its art.
"""
import json
import os
import re

from . import sprite as spritelib

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
GOLD = (246, 200, 60)
GREY = (110, 110, 110)
SHINY = (255, 236, 140)  # brighter than GOLD so the shiny marker stands apart

CELL_GAP = 2

# Visible width has to be measured with escapes stripped; len() counts them.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _c(rgb, text, bold=False):
    return "%s\033[38;2;%d;%d;%dm%s%s" % (
        BOLD if bold else "", rgb[0], rgb[1], rgb[2], text, RESET
    )


def _blank(w, h):
    return [" " * w for _ in range(h)]


def _load_sprite(sprites_dir, pid, shiny=False):
    return spritelib.load(sprites_dir, pid, shiny=shiny)


def _stamp(epoch):
    """'2026-07-30 14:32' -- date and local time of a catch.

    Timestamps have always been stored to the second; only the date was shown.
    """
    import time as _t

    if not epoch:
        return "unknown"
    return _t.strftime("%Y-%m-%d %H:%M", _t.localtime(epoch))


def _silhouette(blob):
    """The 'not caught' look for grid entries.

    Greyscale rather than a single flat tone: a flat silhouette reduces every
    sprite to an outline, and at 21px in a grid most outlines are
    indistinguishable. Keeping the luminance keeps the species recognisable while
    still reading as unowned.
    """
    return spritelib.grayscale(blob, dim=0.7)


def _cell(blob, caption_lines, width, sprite_h):
    """Build one grid cell: art padded to an exact width x sprite_h block.

    Every row must occupy exactly `width` visible columns, including the blank
    ones. Sprites have different heights (blank rows are trimmed at bake time),
    so a short sprite that emitted empty padding rows would let the NEXT cell on
    those lines slide left into the gap -- which shows up as a taller neighbour
    appearing cut in half, its lower rows offset under the shorter one.

    Art is bottom-aligned so Pokemon stand on a common floor rather than hanging
    from the top of their cell.
    """
    art = spritelib.render(blob) if blob else []
    vis = spritelib.visible_width(blob) if blob else 0

    # Trim rather than overflow: a cell wider than its slot pushes the whole row
    # past the terminal edge and wraps, which destroys the art.
    if vis > width:
        art = [_truncate(a, width) for a in art]
        vis = width

    blank = " " * width
    pad = " " * max(0, width - vis)
    rows = [a + pad for a in art[:sprite_h]]
    while len(rows) < sprite_h:
        rows.insert(0, blank)  # bottom-align: pad at the top

    # Captions must occupy the same visible width as the art, or a caption
    # shorter than its cell lets the NEXT cell's caption slide left and the
    # labels stop lining up with the sprites above them.
    for cap in caption_lines:
        vis_cap = len(_ANSI.sub("", cap))
        if vis_cap > width:
            cap = _truncate(cap, width)
            vis_cap = width
        rows.append(cap + " " * (width - vis_cap))
    return rows


def _truncate(line, width):
    """Cut a rendered line to `width` visible columns, keeping escapes intact."""
    out, seen, i = [], 0, 0
    while i < len(line) and seen < width:
        if line[i] == "\033":
            j = line.find("m", i)
            if j == -1:
                break
            out.append(line[i : j + 1])
            i = j + 1
            continue
        out.append(line[i])
        seen += 1
        i += 1
    out.append(RESET)
    return "".join(out)


def fit_columns(term_width, cell_w):
    """How many cells fit without wrapping. Wrapping destroys pixel art, so this
    is a hard constraint rather than a preference."""
    per = cell_w + CELL_GAP
    return max(1, int(term_width + CELL_GAP) // per)


def render_grid(
    entries, sprites_dir, meta, cols=4, cell_w=64, show_uncaught=False, scale=1
):
    """Render one page.

    `entries` is a list of (pid, caught_entry_or_None). Uncaught entries render
    as dim silhouettes when `show_uncaught` is set. `scale` > 1 downsamples
    sprites so more fit per row on a narrow terminal.
    """
    lines = []
    cell_w = cell_w // scale

    for start in range(0, len(entries), cols):
        row = entries[start : start + cols]

        # Load the row's sprites first: heights vary (blank rows are trimmed at
        # bake time), so the cell height has to come from the tallest one in this
        # row rather than being assumed square.
        loaded = []
        for pid, caught in row:
            # Show the shiny colours for a species you own a shiny of -- that is
            # the whole reward, and hiding it in the grid would make shinies
            # invisible unless you knew to open the entry.
            want_shiny = bool(caught and caught.get("shiny"))
            blob = _load_sprite(sprites_dir, pid, shiny=want_shiny)
            if blob is not None and scale > 1:
                blob = spritelib.downscale(blob, scale)
            loaded.append((pid, caught, blob))
        sprite_h = max(
            [(b["h"] + 1) // 2 for _, _, b in loaded if b] or [(cell_w + 1) // 2]
        )

        cells = []
        for pid, caught, blob in loaded:
            info = meta.get(str(pid)) or {}
            name = info.get("name", "?")

            if caught:
                cap_id = _c(GOLD, "#%03d" % pid)
                cap_name = _c(GOLD, name[:cell_w], bold=True)
                extra = caught.get("count", 1)
                cap_x = DIM + ("×%d" % extra if extra > 1 else "") + RESET
                # A star marks the species as one you hold a shiny of. Cheap in
                # width, which matters in a 21-column cell.
                if caught.get("shiny"):
                    cap_x = _c(SHINY, "✧") + cap_x
            else:
                if blob and show_uncaught:
                    blob = _silhouette(blob)
                else:
                    blob = None
                cap_id = _c(GREY, "#%03d" % pid)
                cap_name = DIM + "— — —" + RESET
                cap_x = ""

            cells.append(
                _cell(blob, ["%s %s %s" % (cap_id, cap_name, cap_x)], cell_w, sprite_h)
            )

        height = max(len(c) for c in cells)
        for c in cells:
            while len(c) < height:
                c.append("")
        gap = " " * CELL_GAP
        for i in range(height):
            # No rstrip: the trailing pad on each cell is load-bearing. Stripping
            # it lets a short sprite's blank rows collapse, so the cells to its
            # right shift left on those lines and a taller neighbour looks cut in
            # half. Only the final cell's padding is truly redundant.
            joined = gap.join(c[i] for c in cells)
            lines.append(joined if joined.strip() else "")
        lines.append("")
    return lines


def render_detail(pid, blob, info, caught, roster_ids=None, showing_shiny=False):
    """Large single-entry view.

    An uncaught species renders in greyscale rather than colour, so browsing the
    dex makes it obvious at a glance what you actually own. Greyscale rather than
    a flat silhouette: it keeps the shading, so the Pokemon is still recognisable.
    """
    if blob is not None and not caught:
        blob = spritelib.grayscale(blob)
    art = spritelib.render(blob, indent=2) if blob else []
    name = (info.get("name") or "?").upper()
    types = ", ".join(t.upper() for t in (info.get("types") or []))

    # A text header, not a bare blank line. When this view is re-emitted as a
    # hook systemMessage, Claude Code prepends "PostToolUse:Bash says:" and eats
    # the leading newline -- so whatever is on the first line ends up beside that
    # label. In the grid view that is a harmless text title; here the first line
    # is sprite art, and the top row of the Pokemon gets shunted sideways. A
    # header line takes the hit instead, and names the view while doing it.
    lines = [
        "  " + _c(GOLD, "POKEDEX", bold=True) + DIM + "  ·  entry #%03d" % pid + RESET,
        "",
    ]

    meta_lines = [
        "",
        _c(GOLD, "#%03d %s" % (pid, name), bold=True),
        DIM + types + RESET,
        "",
    ]
    if roster_ids:
        from . import encounter

        tier = encounter.rarity_tier(pid)
        share = encounter.encounter_share(pid, roster_ids)
        colour = GOLD if tier in ("MYTHICAL", "LEGENDARY") else GREY
        pct = ("%.3f" % share).rstrip("0").rstrip(".") if share < 0.1 else "%.2f" % share
        meta_lines.append(
            DIM + "%s%% of encounters" % pct + RESET + "  " + _c(colour, tier)
        )
        meta_lines.append("")
    if caught:
        n = caught.get("count", 1)
        meta_lines.append(_c(GOLD, "CAUGHT") + (_c(GOLD, "  ×%d" % n) if n > 1 else ""))
        meta_lines.append(DIM + "first: %s" % _stamp(caught.get("first", 0)) + RESET)
        if n > 1:
            meta_lines.append(
                DIM + "most recent: %s" % _stamp(caught.get("last", 0)) + RESET
            )
        meta_lines.append(DIM + "times caught: %d" % n + RESET)

        # Shiny is reported separately from the catch count, because the two are
        # independent: owning 5 of a species and 1 shiny of it are both true.
        shinies = caught.get("shiny", 0)
        if shinies:
            from . import encounter

            odds = int(round(1.0 / encounter.SHINY_CHANCE))
            meta_lines.append("")
            meta_lines.append(
                _c(SHINY, "✧ SHINY", bold=True)
                + (_c(SHINY, "  ×%d" % shinies) if shinies > 1 else "")
            )
            meta_lines.append(DIM + "1 in %d per catch" % odds + RESET)
            if caught.get("shiny_first"):
                meta_lines.append(
                    DIM + "first shiny: %s" % _stamp(caught["shiny_first"]) + RESET
                )

            # Name the variant on screen and how to switch. Owning both means the
            # art alone is ambiguous -- some shinies differ only subtly from the
            # normal colours -- and an unlabelled toggle nobody can find is not a
            # toggle.
            owns_normal = caught.get("count", 0) > shinies
            if owns_normal:
                meta_lines.append("")
                if showing_shiny:
                    meta_lines.append(
                        DIM + "showing " + RESET + _c(SHINY, "shiny") + DIM
                        + "  ·  --normal for the ordinary colours" + RESET
                    )
                else:
                    meta_lines.append(
                        DIM + "showing ordinary colours  ·  drop --normal for "
                        + RESET + _c(SHINY, "shiny") + RESET
                    )
    else:
        meta_lines.append(DIM + "not yet caught" + RESET)

    off = max(0, (len(art) - len(meta_lines)) // 2)
    for i in range(max(len(art), len(meta_lines) + off)):
        left = art[i] if i < len(art) else " " * 34
        j = i - off
        right = meta_lines[j] if 0 <= j < len(meta_lines) else ""
        lines.append((left + "   " + right).rstrip())
    return lines
