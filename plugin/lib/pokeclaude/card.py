"""PokeClaude views as image files, for GUIs that will not show the text ones.

Kiro's IDE and Cursor's agent panel put a hook's output through a collapsed,
escape-stripped view: the sprite arrives as a field of identical blocks behind a
disclosure triangle. `mono` mode salvages a silhouette from that, but it is a
consolation prize -- no colour, half the resolution, still collapsed.

Both are VS Code forks, so both have a perfectly good image viewer already built
in, and Cursor's panel additionally renders a markdown image inline. So the art
is drawn as a real PNG and delivered through whichever of those two the host
actually supports:

  inline   the panel renders `![](/abs/path.png)` in the agent's own reply.
           Verified in Cursor. Strictly the best of the three -- the art appears
           where the conversation is, with nothing to open and nothing to expand.
  tab      the editor is asked to open the file (`cursor -r`, `kiro -r`). Costs a
           tab, but needs no cooperation from the agent, which is what makes it
           the only option for a turn-end hook: by the time a catch happens the
           agent has already finished speaking and cannot be asked to say more.

Catches use `tab` because a hook has no other reach. The Pokedex uses `inline`
where the host supports it, because a browsing command IS an agent turn.

Card paths are deliberately STABLE (`latest-catch.png`, `pokedex.png`). VS Code's
media preview watches the file it is showing and re-renders on change -- measured
in Cursor's bundled copy -- so one tab keeps updating for the whole session
instead of accumulating one per catch.
"""
import os
import subprocess
import sys

from . import banner, hosts, sprite as spritelib

# Layout, in output pixels. The sprite is drawn at 6x because an image has no
# 10,000-character cap to respect -- unlike the text banner, which has to halve
# the art to fit through a systemMessage.
SPRITE_PX = 6
PAD = 28
GAP = 32
BAR = 8  # accent stripe down the left edge
BODY_SCALE = 3  # 5x7 font at 3x -> 15x21 glyphs
TITLE_SCALE = 4
LEADING = 12
SPACER = 16

# Grid cells. Smaller sprites than a single-entry view, since a page of them has
# to stay a sensible width, but still far above what the terminal grid manages.
GRID_PX = 3
GRID_CAPTION = 2
GRID_GAP = 20
GRID_CAPTION_CHARS = 17  # what fits under a 64px sprite at these scales

# An opaque panel rather than transparency: the image viewer shows transparent
# pixels as a checkerboard, which would sit under the text and wreck it. Dark
# charcoal reads correctly in both the light and dark editor themes because the
# card brings its own background with it.
BG = (22, 23, 31)
DIM = (124, 128, 145)
GREY = (92, 96, 110)

FILENAME = "latest-catch.png"
FILENAME_DEX = "pokedex.png"


def default_path(filename=FILENAME):
    from . import store

    return os.path.join(store.ROOT, filename)


def fallback_path(filename=FILENAME):
    """Where to put a card when the collection directory cannot be written.

    Sandboxed hosts are the reason. The Codex app lets a tool READ anywhere --
    the Pokedex and the config both load -- but confines writes to the
    workspace, so `~/.claude/pokeclaude/` is off limits. The failure is silent by
    construction: a card that cannot be drawn falls back to text rather than
    breaking the command, which makes a sandbox look exactly like a host that
    does not support images.

    The temp directory is writable in that sandbox, and a card there renders the
    same -- measured, an image under /var/folders displays inline correctly.
    """
    import tempfile

    return os.path.join(tempfile.gettempdir(), "pokeclaude", filename)


def host_path(filename=FILENAME, host=None):
    """Beside the host's own configuration, e.g. ~/.codex/pokeclaude/.

    Tried before the temp directory because it is a real home for the file
    rather than scratch space: it survives a reboot, it is obvious where it came
    from, and a host that sandboxes a tool to its own tree may well allow it.
    """
    d = hosts.spec(host).get("config_dir")
    if not d:
        return None
    return os.path.join(os.path.expanduser(d), "pokeclaude", filename)


def _candidates(filename, path=None, host=None):
    """Paths to try, in order. An explicit path is taken as given.

    Ordered by how good a home each is, not by likelihood of success: the
    collection directory keeps the card with everything else PokeClaude owns,
    the host's own directory is the next most sensible place, and the temp
    directory is the last resort that a sandbox will almost always permit.
    """
    if path:
        return [path]
    out = [default_path(filename), host_path(filename, host),
           fallback_path(filename)]
    seen = []
    for p in out:
        if p and p not in seen:
            seen.append(p)
    return seen


def _bbox(blob):
    """Tight bounds of the opaque pixels: (x0, y0, x1, y1), or None if blank."""
    _, rows = spritelib.decode(blob)
    xs = [
        x
        for x in range(blob["w"])
        if any(r[x] != spritelib.TRANSPARENT for r in rows)
    ]
    ys = [y for y, r in enumerate(rows) if any(v != spritelib.TRANSPARENT for v in r)]
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _rarity_line(dex_id, roster_ids):
    """The '0.013% OF ENCOUNTERS  LEGENDARY' row, or None without a roster."""
    if not roster_ids:
        return None
    from . import encounter

    tier = encounter.rarity_tier(dex_id)
    share = encounter.encounter_share(dex_id, roster_ids)
    share_txt = (
        ("%.3f" % share).rstrip("0").rstrip(".") if share < 0.1 else "%.2f" % share
    )
    tint = banner.GOLD if tier in ("MYTHICAL", "LEGENDARY") else banner.SILVER
    return [("%s%% OF ENCOUNTERS  " % share_txt, DIM), (tier, tint)]


def _type_segments(type_names):
    return [
        seg
        for t in type_names
        for seg in ((t.upper(), banner.TYPE_RGB.get(t, DIM)), ("  ", DIM))
    ]


def _measure(lines):
    from . import image

    width = 0
    height = 0
    for scale, segs in lines:
        if not segs:
            height += SPACER
            continue
        width = max(width, sum(image.text_width(t, scale) for t, _ in segs))
        height += image.GLYPH_H * scale + LEADING
    return width, max(0, height - LEADING)


def _panel(lines, blob=None, accent=None):
    """A sprite beside a text column, on the standard card background.

    Shared by the catch banner and the Pokedex detail view: they differ only in
    what goes in the text column, and a second layout would have meant two things
    to keep visually in step.
    """
    from . import image

    accent = accent or banner.GOLD
    text_w, text_h = _measure(lines)

    box = _bbox(blob) if blob else None
    if box is None:
        art_w = art_h = 0
    else:
        x0, y0, x1, y1 = box
        art_w = (x1 - x0 + 1) * SPRITE_PX
        art_h = (y1 - y0 + 1) * SPRITE_PX

    w = BAR + PAD + art_w + (GAP if art_w else 0) + text_w + PAD
    h = max(art_h, text_h) + 2 * PAD
    canvas = image.Canvas(w, h, BG)
    canvas.rect(0, 0, BAR, h, accent)

    if box is not None:
        pal, rows = spritelib.decode(blob)
        left = BAR + PAD
        top = PAD + max(0, (h - 2 * PAD - art_h) // 2)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                colour = pal[rows[y][x]]
                if colour is None:
                    continue
                canvas.rect(
                    left + (x - x0) * SPRITE_PX,
                    top + (y - y0) * SPRITE_PX,
                    SPRITE_PX, SPRITE_PX, colour,
                )

    tx = BAR + PAD + art_w + (GAP if art_w else 0)
    ty = PAD + max(0, (h - 2 * PAD - text_h) // 2)
    for scale, segs in lines:
        if not segs:
            ty += SPACER
            continue
        x = tx
        for text, rgb in segs:
            x += canvas.text(x, ty, text, rgb, scale)
        ty += image.GLYPH_H * scale + LEADING

    return canvas


# --- the catch banner --------------------------------------------------------


def _lines_catch(name, dex_id, type_names, is_new, dup_count, unique, roster_size,
                 roster_ids, shiny):
    """The catch card's text column.

    Mirrors `banner.compose` line for line, so the image and the text banner say
    the same things in the same order -- a host that shows both should not look
    like it caught two different Pokemon.
    """
    accent = banner.GOLD if (is_new or shiny) else banner.SILVER
    out = [
        (TITLE_SCALE, [
            ("A WILD %s%s APPEARED!" % ("SHINY " if shiny else "", name.upper()),
             accent),
        ]),
        (BODY_SCALE, []),
        (BODY_SCALE, [("#%03d" % dex_id, accent), ("  ", DIM)]
                     + _type_segments(type_names)),
    ]

    if is_new:
        out.append((BODY_SCALE, [("NEW - ADDED TO YOUR POKEDEX", banner.GOLD)]))
    else:
        out.append((BODY_SCALE, [("DUPLICATE X%d" % dup_count, banner.SILVER)]))

    if shiny:
        from . import encounter

        odds = int(round(1.0 / encounter.SHINY_CHANCE))
        out.append((BODY_SCALE, [
            ("* SHINY", banner.SHINY), ("  1 IN %d" % odds, DIM),
        ]))

    rarity = _rarity_line(dex_id, roster_ids)
    if rarity:
        out.append((BODY_SCALE, rarity))

    pct = (100.0 * unique / roster_size) if roster_size else 0.0
    out.append((BODY_SCALE, []))
    out.append((BODY_SCALE, [
        ("POKEDEX %d/%d (%.0f%%)" % (unique, roster_size, pct), DIM),
    ]))
    return out


def compose(blob, name, dex_id, type_names, is_new, dup_count, unique,
            roster_size, roster_ids=None, shiny=False):
    """Draw the catch card. Returns an `image.Canvas`."""
    return _panel(
        _lines_catch(name, dex_id, type_names, is_new, dup_count, unique,
                     roster_size, roster_ids, shiny),
        blob,
        accent=banner.GOLD if (is_new or shiny) else banner.SILVER,
    )


# --- the Pokedex -------------------------------------------------------------


def detail(pid, blob, info, caught, roster_ids=None, showing_shiny=False):
    """The single-entry view: `pokedex.py --id N` as an image."""
    from . import dex

    name = (info.get("name") or "?").upper()
    accent = banner.GOLD if caught else GREY
    if blob is not None and not caught:
        blob = spritelib.grayscale(blob)

    lines = [
        (TITLE_SCALE, [("#%03d %s" % (pid, name), accent)]),
        (BODY_SCALE, []),
        (BODY_SCALE, _type_segments(info.get("types") or []) or [("?", DIM)]),
    ]
    rarity = _rarity_line(pid, roster_ids)
    if rarity:
        lines.append((BODY_SCALE, rarity))
    lines.append((BODY_SCALE, []))

    if caught:
        n = caught.get("count", 1)
        lines.append((BODY_SCALE, [
            ("CAUGHT" + ("  X%d" % n if n > 1 else ""), banner.GOLD),
        ]))
        lines.append((BODY_SCALE, [("FIRST %s" % dex._stamp(caught.get("first", 0)), DIM)]))
        if n > 1:
            lines.append((BODY_SCALE, [
                ("LATEST %s" % dex._stamp(caught.get("last", 0)), DIM),
            ]))

        shinies = caught.get("shiny", 0)
        if shinies:
            from . import encounter

            odds = int(round(1.0 / encounter.SHINY_CHANCE))
            lines.append((BODY_SCALE, []))
            lines.append((BODY_SCALE, [
                ("* SHINY" + ("  X%d" % shinies if shinies > 1 else ""), banner.SHINY),
                ("  1 IN %d" % odds, DIM),
            ]))
            if caught.get("count", 0) > shinies:
                lines.append((BODY_SCALE, [
                    ("SHOWING %s COLOURS"
                     % ("SHINY" if showing_shiny else "ORDINARY"), DIM),
                ]))
    else:
        lines.append((BODY_SCALE, [("NOT YET CAUGHT", DIM)]))

    return _panel(lines, blob, accent=accent)


def grid(entries, sprites_dir, meta, cols=6, show_uncaught=False, title=None,
         footer=None):
    """A page of the collection as an image.

    The terminal grid is capped at four entries per page, for a reason that
    simply does not apply here: a hook `systemMessage` is hard-limited to 10,000
    characters, and colour escapes are ~88% of a rendered sprite's bytes. An
    image has no such ceiling, so a page can hold a whole screenful.
    """
    from . import image

    cell_w = 64 * GRID_PX
    caption_h = image.GLYPH_H * GRID_CAPTION

    # Load first: sprite heights vary (blank rows are trimmed at bake time), so a
    # row's height has to come from its tallest member rather than be assumed.
    loaded = []
    for pid, caught in entries:
        want_shiny = bool(caught and caught.get("shiny"))
        blob = spritelib.load(sprites_dir, pid, shiny=want_shiny)
        if blob is not None and not caught:
            blob = spritelib.grayscale(blob, dim=0.7) if show_uncaught else None
        loaded.append((pid, caught, blob))

    rows = [loaded[i:i + cols] for i in range(0, len(loaded), cols)]
    row_art_h = []
    for row in rows:
        heights = []
        for _, _, blob in row:
            box = _bbox(blob) if blob else None
            heights.append(((box[3] - box[1] + 1) * GRID_PX) if box else 0)
        row_art_h.append(max(heights or [0]))

    head_h = (image.GLYPH_H * BODY_SCALE + LEADING) if title else 0
    # Twice the leading under the footer: one row's captions already sit a single
    # leading below its art, so a single gap here reads as the last caption and
    # the page number colliding.
    foot_h = (image.GLYPH_H * GRID_CAPTION + 2 * LEADING) if footer else 0
    w = BAR + PAD + cols * cell_w + (cols - 1) * GRID_GAP + PAD
    h = (
        2 * PAD + head_h + foot_h
        + sum(row_art_h) + len(rows) * (caption_h + LEADING + GRID_GAP)
        - (GRID_GAP if rows else 0)
    )
    canvas = image.Canvas(w, max(h, 2 * PAD + 40), BG)
    canvas.rect(0, 0, BAR, canvas.h, banner.GOLD)

    left0 = BAR + PAD
    y = PAD
    if title:
        x = left0
        for text, rgb in title:
            x += canvas.text(x, y, text, rgb, BODY_SCALE)
        y += image.GLYPH_H * BODY_SCALE + LEADING

    for row, art_h in zip(rows, row_art_h):
        for n, (pid, caught, blob) in enumerate(row):
            cx = left0 + n * (cell_w + GRID_GAP)
            box = _bbox(blob) if blob else None
            if box is not None:
                x0, y0, x1, y1 = box
                pal, prows = spritelib.decode(blob)
                # Centred in its cell, and bottom-aligned across the row, so a
                # short sprite does not float above its caption.
                ox = cx + (cell_w - (x1 - x0 + 1) * GRID_PX) // 2
                oy = y + art_h - (y1 - y0 + 1) * GRID_PX
                for py in range(y0, y1 + 1):
                    for px in range(x0, x1 + 1):
                        colour = pal[prows[py][px]]
                        if colour is None:
                            continue
                        canvas.rect(
                            ox + (px - x0) * GRID_PX, oy + (py - y0) * GRID_PX,
                            GRID_PX, GRID_PX, colour,
                        )

            info = meta.get(str(pid)) or {}
            name = (info.get("name") or "?").upper()
            if caught:
                count = caught.get("count", 1)
                cap = "#%03d %s" % (pid, name)
                extra = ("*" if caught.get("shiny") else "") + (
                    "X%d" % count if count > 1 else ""
                )
                colour = banner.SHINY if caught.get("shiny") else banner.GOLD
            else:
                cap, extra, colour = "#%03d ---" % pid, "", GREY
            cap = cap[:GRID_CAPTION_CHARS - len(extra) - (1 if extra else 0)]
            cy = y + art_h + LEADING
            used = canvas.text(cx, cy, cap, colour, GRID_CAPTION)
            if extra:
                canvas.text(
                    cx + used + image.ADVANCE * GRID_CAPTION, cy, extra,
                    banner.SHINY if caught and caught.get("shiny") else DIM,
                    GRID_CAPTION,
                )
        y += art_h + caption_h + LEADING + GRID_GAP

    if footer:
        x = left0
        for text, rgb in footer:
            x += canvas.text(x, canvas.h - PAD - image.GLYPH_H * GRID_CAPTION,
                             text, rgb, GRID_CAPTION)
    return canvas


# --- delivery ----------------------------------------------------------------


def write_canvas(path, canvas):
    """Save a canvas to `path`, atomically, overwriting whatever was there.

    The rename matters twice over. It keeps a reader from catching a half-written
    PNG, which the editor's preview would draw as a broken image; and it means
    these views never accumulate. There are exactly two card files, each
    overwritten in place -- a session's hundredth catch costs the same ~10KB as
    its first.
    """
    data = canvas.to_png()
    tmp = "%s.tmp%d" % (path, os.getpid())
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.rename(tmp, path)
    except Exception:
        # A failed write must not leave its scratch file behind, or the one thing
        # this directory is supposed to never do -- grow -- is exactly what it
        # does, one orphan per crash.
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path


def write(path, **facts):
    """Render a catch card to `path`."""
    return write_canvas(path, compose(**facts))


def viewer_argv(path, host=None, which=None, platform=None):
    """The command that opens `path` in this host's editor, or None.

    Prefers the host's own CLI (`kiro --reuse-window`, the VS Code convention its
    fork inherits) because it targets the running window directly. On macOS an
    installed CLI is not a given -- it is an opt-in step in the command palette --
    so `open -a` is the fallback. `-g` keeps the editor from stealing focus if the
    user has tabbed away to something else.
    """
    view = hosts.spec(host).get("viewer")
    if not view:
        return None

    if which is None:
        import shutil

        which = shutil.which
    platform = platform if platform is not None else sys.platform

    cli = view.get("cli")
    if cli and which(cli):
        return [cli, "--reuse-window", path]
    if view.get("app") and platform == "darwin":
        return ["open", "-g", "-a", view["app"], path]
    return None


def open_path(path, host=None):
    """Ask the host's editor to show `path`. True if a launcher was spawned."""
    argv = viewer_argv(path, host)
    if argv is None:
        return False
    subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # Detached, so a hook killed at its timeout does not take the editor
        # launch down with it.
        start_new_session=True,
    )
    return True


def show_canvas(canvas, filename=FILENAME, host=None, path=None):
    """Write a canvas and open it in the editor. Returns the path, or None.

    None means the caller should fall back to text: either this host has no
    viewer, or writing/launching failed. Never raises -- a view that cannot be
    drawn is a missed picture, not a broken command.
    """
    for candidate in _candidates(filename, path, host):
        try:
            if viewer_argv(candidate, host) is None:
                return None
            write_canvas(candidate, canvas)
            return candidate if open_path(candidate, host) else None
        except Exception:
            continue
    return None


def write_inline(canvas, filename=FILENAME_DEX, path=None, host=None):
    """Write a canvas for a host that renders markdown images. Path, or None.

    No launcher: the agent puts `![](path)` in its own reply and the panel draws
    it there. Verified in Cursor with a bare absolute path -- no `file://` scheme,
    which that renderer does not accept.
    """
    for candidate in _candidates(filename, path, host):
        try:
            return write_canvas(candidate, canvas)
        except Exception:
            continue
    return None


def show(blob, host=None, path=None, **facts):
    """Write the catch card and open it. True if it should now be on screen."""
    try:
        return show_canvas(
            compose(blob=blob, **facts), FILENAME, host=host, path=path
        ) is not None
    except Exception:
        return False
