"""Sprite codec and half-block terminal renderer.

A baked sprite is a small JSON blob: a palette of up to 15 opaque colours plus
a nibble-per-pixel index grid, where index 0 means transparent. Rendering pairs
vertically adjacent pixel rows into a single terminal row using the upper-half
block U+2580: the glyph's foreground paints the top pixel, its background the
bottom one. That yields square-ish pixels at 2x vertical density.

Storage is ~550 bytes per sprite, so the whole Gen 1-3 roster fits in ~210KB
and a catch only ever reads the one file it needs.
"""

TRANSPARENT = 0

# Half-block glyphs. Foreground is always the *upper* pixel.
UPPER = "▀"  # ▀ top half painted in fg, bottom half in bg
LOWER = "▄"  # ▄ bottom half painted in fg, top half in bg

RESET = "\033[0m"
DEFAULT_BG = "\033[49m"


def _fg(rgb):
    return "\033[38;2;%d;%d;%dm" % rgb


def _bg(rgb):
    return "\033[48;2;%d;%d;%dm" % rgb


def decode(blob):
    """Expand a baked sprite into (palette, rows-of-indices).

    palette[0] is None (transparent); palette[i] is an (r, g, b) tuple.
    """
    w, h = blob["w"], blob["h"]
    pal = [None]
    for hexcol in blob["pal"]:
        pal.append(
            (int(hexcol[0:2], 16), int(hexcol[2:4], 16), int(hexcol[4:6], 16))
        )
    flat = [int(c, 16) for c in blob["px"]]
    if len(flat) != w * h:
        raise ValueError(
            "sprite %s: expected %d px, got %d" % (blob.get("id"), w * h, len(flat))
        )
    return pal, [flat[y * w : (y + 1) * w] for y in range(h)]


def render(blob, indent=0, trim=True):
    """Render a baked sprite to a list of ANSI strings, one per terminal row.

    Rows are emitted top-down. Fully transparent leading/trailing columns are
    dropped when `trim` is set, so a narrow sprite does not carry dead padding.
    """
    pal, rows = decode(blob)
    h = len(rows)
    if h % 2:  # half-blocks consume rows in pairs
        rows = rows + [[TRANSPARENT] * blob["w"]]
        h += 1

    x0, x1 = 0, blob["w"] - 1
    if trim:
        cols = [
            x
            for x in range(blob["w"])
            if any(r[x] != TRANSPARENT for r in rows)
        ]
        if not cols:
            return []
        x0, x1 = min(cols), max(cols)

    pad = " " * indent
    out = []
    for y in range(0, h, 2):
        top, bot = rows[y], rows[y + 1]
        line = []
        for x in range(x0, x1 + 1):
            t, b = pal[top[x]], pal[bot[x]]
            if t is None and b is None:
                line.append(" ")
            elif b is None:
                line.append(_fg(t) + DEFAULT_BG + UPPER + RESET)
            elif t is None:
                line.append(_fg(b) + DEFAULT_BG + LOWER + RESET)
            else:
                line.append(_fg(t) + _bg(b) + UPPER + RESET)
        out.append(pad + "".join(line))
    return out


def visible_width(blob, trim=True):
    """Columns a rendered sprite occupies, ignoring escape sequences."""
    _, rows = decode(blob)
    if not trim:
        return blob["w"]
    cols = [
        x for x in range(blob["w"]) if any(r[x] != TRANSPARENT for r in rows)
    ]
    return (max(cols) - min(cols) + 1) if cols else 0


def downscale(blob, factor=2):
    """Halve a sprite's resolution for grid views.

    Each output pixel takes the most common opaque colour in its factor x factor
    source block, so silhouettes stay solid instead of dissolving into gaps the
    way naive point-sampling would. A block that is mostly transparent stays
    transparent, which preserves the outline.
    """
    if factor <= 1:
        return blob
    pal, rows = decode(blob)
    w, h = blob["w"], blob["h"]
    nw, nh = w // factor, h // factor

    out = []
    for y in range(nh):
        for x in range(nw):
            counts = {}
            opaque = 0
            for dy in range(factor):
                for dx in range(factor):
                    sy, sx = y * factor + dy, x * factor + dx
                    if sy >= h or sx >= w:
                        continue
                    idx = rows[sy][sx]
                    if idx == TRANSPARENT:
                        continue
                    opaque += 1
                    counts[idx] = counts.get(idx, 0) + 1
            # Keep the pixel only if the block is at least a third covered;
            # below that it is edge fringe and dropping it keeps edges crisp.
            if not counts or opaque * 3 < factor * factor:
                out.append(TRANSPARENT)
            else:
                out.append(max(counts.items(), key=lambda kv: kv[1])[0])

    return {
        "id": blob.get("id"),
        "w": nw,
        "h": nh,
        "pal": list(blob["pal"]),
        "px": "".join("%x" % i for i in out),
    }
