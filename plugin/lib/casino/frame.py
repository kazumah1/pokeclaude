"""Truecolor half-block renderer.

A grid is rows of pixels; a pixel is None (transparent) or (r, g, b). Rendering
pairs two vertically adjacent pixel rows into one terminal row using U+2580 ▀:
the glyph's foreground paints the top pixel, its background the bottom one, so
pixels come out roughly square at 2x vertical density. Transparent pixels fall
through to `bg`.
"""
UPPER = "▀"  # ▀
RESET = "\x1b[0m"


def _fg(rgb):
    return "\x1b[38;2;%d;%d;%dm" % rgb


def _bg(rgb):
    return "\x1b[48;2;%d;%d;%dm" % rgb


def blank(w, h, fill=None):
    return [[fill for _ in range(w)] for _ in range(h)]


def stamp(grid, bitmap, ox, oy, color):
    """Paint the '1' cells of a list-of-strings bitmap onto grid at (ox, oy)."""
    for j, row in enumerate(bitmap):
        for i, ch in enumerate(row):
            if ch == "1":
                y, x = oy + j, ox + i
                if 0 <= y < len(grid) and 0 <= x < len(grid[y]):
                    grid[y][x] = color


def _width(grid):
    return max((len(r) for r in grid), default=0)


def hconcat(grids, gap=2, bg=None):
    h = max(len(g) for g in grids)
    total = sum(_width(g) for g in grids) + gap * (len(grids) - 1)
    out = blank(total, h, bg)
    x = 0
    for g in grids:
        gw = _width(g)
        for j in range(len(g)):
            for i in range(len(g[j])):
                out[j][x + i] = g[j][i]
        x += gw + gap
    return out


def vconcat(grids, gap=1, bg=None):
    w = max(_width(g) for g in grids)
    out = []
    for idx, g in enumerate(grids):
        for row in g:
            out.append(list(row) + [bg] * (w - len(row)))
        if idx != len(grids) - 1:
            out.extend(blank(w, gap, bg))
    return out


def scale(grid, k):
    out = []
    for row in grid:
        big_row = []
        for px in row:
            big_row.extend([px] * k)
        for _ in range(k):
            out.append(list(big_row))
    return out


def render(grid, bg=(0, 0, 0)):
    if not grid:
        return ""
    w = _width(grid)
    h = len(grid)

    def px(y, x):
        if 0 <= y < h and x < len(grid[y]):
            p = grid[y][x]
            return p if p is not None else bg
        return bg

    lines = []
    for y in range(0, h, 2):
        parts = []
        for x in range(w):
            parts.append(_fg(px(y, x)) + _bg(px(y + 1, x)) + UPPER)
        lines.append("".join(parts) + RESET)
    return "\n".join(lines)
