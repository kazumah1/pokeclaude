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

from . import sprite as spritelib

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
GOLD = (246, 200, 60)
GREY = (110, 110, 110)

CELL_GAP = 2


def _c(rgb, text, bold=False):
    return "%s\033[38;2;%d;%d;%dm%s%s" % (
        BOLD if bold else "", rgb[0], rgb[1], rgb[2], text, RESET
    )


def _blank(w, h):
    return [" " * w for _ in range(h)]


def _load_sprite(sprites_dir, pid):
    try:
        with open(os.path.join(sprites_dir, "%d.json" % pid)) as f:
            return json.load(f)
    except (IOError, OSError, ValueError):
        return None


def _silhouette(blob, rgb=(58, 58, 64)):
    """Recolour every opaque pixel to a single dim tone: the classic
    'seen but not caught' look for uncaught entries."""
    out = dict(blob)
    out["pal"] = ["%02x%02x%02x" % rgb] * len(blob["pal"])
    return out


def _cell(blob, caption_lines, width, sprite_h):
    art = spritelib.render(blob) if blob else _blank(width, sprite_h)
    art = [a for a in art]
    while len(art) < sprite_h:
        art.append("")
    # Pad art rows to a fixed visible width. Escape sequences make len()
    # unreliable, so pad by the sprite's known pixel width instead.
    vis = spritelib.visible_width(blob) if blob else width
    pad = " " * max(0, width - vis)
    rows = [a + pad for a in art[:sprite_h]]
    for cap in caption_lines:
        rows.append(cap)
    return rows


def fit_columns(term_width, cell_w):
    """How many cells fit without wrapping. Wrapping destroys pixel art, so this
    is a hard constraint rather than a preference."""
    per = cell_w + CELL_GAP
    return max(1, int(term_width + CELL_GAP) // per)


def render_grid(
    entries, sprites_dir, meta, cols=4, cell_w=32, show_uncaught=False, scale=1
):
    """Render one page.

    `entries` is a list of (pid, caught_entry_or_None). Uncaught entries render
    as dim silhouettes when `show_uncaught` is set. `scale` > 1 downsamples
    sprites so more fit per row on a narrow terminal.
    """
    lines = []
    cell_w = cell_w // scale
    sprite_h = (cell_w + 1) // 2  # half-blocks: two pixel rows per text row

    for start in range(0, len(entries), cols):
        row = entries[start : start + cols]
        cells = []
        for pid, caught in row:
            blob = _load_sprite(sprites_dir, pid)
            if blob is not None and scale > 1:
                blob = spritelib.downscale(blob, scale)
            info = meta.get(str(pid)) or {}
            name = info.get("name", "?")

            if caught:
                cap_id = _c(GOLD, "#%03d" % pid)
                cap_name = _c(GOLD, name[:cell_w], bold=True)
                extra = caught.get("count", 1)
                cap_x = DIM + ("×%d" % extra if extra > 1 else "") + RESET
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
            lines.append(gap.join(c[i] for c in cells).rstrip())
        lines.append("")
    return lines


def render_detail(pid, blob, info, caught):
    """Large single-entry view."""
    lines = [""]
    art = spritelib.render(blob, indent=2) if blob else []
    name = (info.get("name") or "?").upper()
    types = ", ".join(t.upper() for t in (info.get("types") or []))

    meta_lines = [
        "",
        _c(GOLD, "#%03d %s" % (pid, name), bold=True),
        DIM + types + RESET,
        "",
    ]
    if caught:
        import time as _t

        n = caught.get("count", 1)
        first = _t.strftime("%Y-%m-%d", _t.localtime(caught.get("first", 0)))
        meta_lines.append(_c(GOLD, "CAUGHT") + (_c(GOLD, "  ×%d" % n) if n > 1 else ""))
        meta_lines.append(DIM + "first: %s" % first + RESET)
        if n > 1:
            last = _t.strftime("%Y-%m-%d", _t.localtime(caught.get("last", 0)))
            meta_lines.append(DIM + "most recent: %s" % last + RESET)
        meta_lines.append(DIM + "times caught: %d" % n + RESET)
    else:
        meta_lines.append(DIM + "not yet caught" + RESET)

    off = max(0, (len(art) - len(meta_lines)) // 2)
    for i in range(max(len(art), len(meta_lines) + off)):
        left = art[i] if i < len(art) else " " * 34
        j = i - off
        right = meta_lines[j] if 0 <= j < len(meta_lines) else ""
        lines.append((left + "   " + right).rstrip())
    return lines
