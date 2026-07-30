#!/usr/bin/env python3
"""Build animated GIF demos of what PokeClaude catches could look like.

This is a DEMO generator, not a plugin feature. The catch banner itself cannot
animate -- it is written once to the terminal's immutable scrollback through a
hook `systemMessage`, and hooks cannot reach `/dev/tty` to repaint. So animation
only makes sense on the README, where a GIF plays anywhere GitHub renders an
image. This script shows what that would look like.

Frames are built from the real baked sprites via the same half-block model the
plugin renders with, so a demo cannot depict art the plugin could not actually
produce. Each frame is rasterised with rsvg-convert and the frames are muxed into
a GIF with Pillow.

    python3 tools/animate_demo.py --style reveal --id 143 --out docs/anim-catch.gif
    python3 tools/animate_demo.py --style bob    --id 25  --out docs/anim-bob.gif
    python3 tools/animate_demo.py --style sparkle --id 150 --out docs/anim-shiny.gif
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "plugin", "lib"))
sys.path.insert(0, os.path.join(REPO, "tools"))

from pokeclaude import banner, sprite as spritelib  # noqa: E402

import ansi_to_svg as a2s  # noqa: E402

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow required: pip3 install Pillow")

ASSETS = os.path.join(REPO, "plugin", "assets")
META = json.load(open(os.path.join(ASSETS, "pokemon.json")))
ROSTER = sorted(int(k) for k in META)


def load(pid):
    return json.load(open(os.path.join(ASSETS, "sprites", "%d.json" % pid)))


def scale_palette(blob, factor):
    """Multiply every palette colour by `factor`, for fade-in/out frames."""
    out = dict(blob)
    pal = []
    for hexcol in blob["pal"]:
        r = int(hexcol[0:2], 16)
        g = int(hexcol[2:4], 16)
        b = int(hexcol[4:6], 16)
        pal.append(
            "%02x%02x%02x"
            % tuple(max(0, min(255, int(round(c * factor)))) for c in (r, g, b))
        )
    out["pal"] = pal
    return out


def brighten(blob, add):
    """Add a flat white amount to every palette colour, for a sparkle flash."""
    out = dict(blob)
    pal = []
    for hexcol in blob["pal"]:
        r = int(hexcol[0:2], 16)
        g = int(hexcol[2:4], 16)
        b = int(hexcol[4:6], 16)
        pal.append(
            "%02x%02x%02x"
            % tuple(max(0, min(255, c + add)) for c in (r, g, b))
        )
    out["pal"] = pal
    return out


def banner_text(blob, pid, is_new=True):
    info = META[str(pid)]
    return banner.compose(
        blob, info["name"], pid, info["types"], is_new, 1, 1, len(ROSTER),
        width=80, roster_ids=ROSTER,
    )


def frames_reveal(pid):
    """Catch reveal: the sprite fades up from the dark canvas as text holds."""
    blob = load(pid)
    out = []
    # ease-in fade, then a couple of held frames on the finished banner
    for f in (0.0, 0.12, 0.28, 0.5, 0.78, 1.0):
        out.append(banner_text(scale_palette(blob, f), pid))
    out += [banner_text(blob, pid)] * 6  # hold
    return out, 90


# A Pokeball, drawn as a sprite blob so it goes through the identical renderer as
# every Pokemon -- same half-block model, same palette encoding. Hand-authored
# rather than fetched: PokeAPI has no ball sprite, and at this size a 16x16 grid
# is more legible than downscaled item art.
#
# Palette: 1 red, 2 dark red, 3 white, 4 grey, 5 black, 6 highlight.
_BALL_PAL = [
    "e03a2f",  # 1 red
    "8f1f18",  # 2 red shadow
    "f2f2f2",  # 3 white
    "b9bec4",  # 4 white shadow
    "141414",  # 5 outline / seam
    "ff8f86",  # 6 red highlight
]
# Shaded rather than two flat bands: the sprites it sits beside all carry interior
# shading, and a flat silhouette reads as a placeholder next to them. Light comes
# from the upper left, matching the sprite art.
_BALL_ART = [
    "0000055555550000",
    "0005566111112500",
    "0056611111112250",
    "0561111111111225",
    "5611111111111225",
    "5111111111111122",
    "5111111111111222",
    "5555555555555555",
    "5333333333333444",
    "5333355553334444",
    "5333533335334444",
    "0533533335344440",
    "0053355553444400",
    "0005333334444000",
    "0000544444400000",
    "0000000000000000",
]


def ball_blob(shake=0, open_amount=0):
    """The ball as a sprite blob.

    `shake` nudges the whole ball horizontally by that many pixels, for the
    wobble before it opens. `open_amount` (0-3) splits it along the seam and
    slides the halves apart, which is what reads as "opening".
    """
    rows = [list(r) for r in _BALL_ART]
    w = len(rows[0])

    if open_amount:
        top = rows[:8]
        bottom = rows[8:]
        blank = ["0"] * w
        # Push the halves apart, keeping total height fixed so the frame does not
        # jump; the gap is where the Pokemon will emerge from.
        top = [blank] * 0 + top[open_amount:] + [blank] * open_amount
        bottom = [blank] * open_amount + bottom[: len(bottom) - open_amount]
        rows = top + bottom

    if shake:
        out = []
        for r in rows:
            if shake > 0:
                out.append(["0"] * shake + r[:-shake])
            else:
                out.append(r[-shake:] + ["0"] * (-shake))
        rows = out

    return {
        "id": "ball",
        "w": w,
        "h": len(rows),
        "pal": list(_BALL_PAL),
        "px": "".join("".join(r) for r in rows),
    }


def scale_up(blob, factor):
    """Nearest-neighbour upscale, so a small hand-drawn blob matches sprite scale.

    The ball is authored on a 16x16 grid for legibility, but a sprite is 32x32 at
    grid scale. Without this the ball renders visibly tiny beside the Pokemon it
    is supposed to contain.
    """
    if factor <= 1:
        return blob
    w, h = blob["w"], blob["h"]
    rows = [blob["px"][y * w : (y + 1) * w] for y in range(h)]
    out = []
    for r in rows:
        wide = "".join(c * factor for c in r)
        out.extend([wide] * factor)
    return {
        "id": blob.get("id"),
        "w": w * factor,
        "h": h * factor,
        "pal": list(blob["pal"]),
        "px": "".join(out),
    }


def _pad_to(blob, width, height):
    """Centre a blob on a larger transparent canvas, so frames share a size."""
    w, h = blob["w"], blob["h"]
    if w >= width and h >= height:
        return blob
    width, height = max(w, width), max(h, height)
    ox = (width - w) // 2
    oy = height - h  # sit on the floor, like the sprites do
    rows = [blob["px"][y * w : (y + 1) * w] for y in range(h)]
    out = ["0" * width] * oy
    for r in rows:
        out.append("0" * ox + r + "0" * (width - w - ox))
    out += ["0" * width] * (height - h - oy)
    return {
        "id": blob.get("id"),
        "w": width,
        "h": height,
        "pal": list(blob["pal"]),
        "px": "".join(out),
    }


def frames_ball(pid):
    """Pokeball throw -> wobble -> open -> Pokemon revealed.

    The whole sequence is composed at one canvas size so nothing resizes
    mid-animation: the ball is padded onto the sprite's footprint, and the sprite
    fades up out of the opened ball's position.
    """
    sprite_blob = spritelib.downscale(load(pid), 2)
    sw, sh = sprite_blob["w"], sprite_blob["h"]

    # Match the ball to the sprite's scale, then pad it onto the sprite's exact
    # footprint so the Pokemon emerges from where the ball actually was.
    def ball(**kw):
        return _pad_to(scale_up(ball_blob(**kw), 2), sw, sh)

    frames = []

    # 1. Ball sits closed, then wobbles: the classic "is it caught?" beat. Held
    #    frames are duplicated deliberately -- GIF optimisers collapse identical
    #    consecutive frames, so a beat has to be earned with distinct timing
    #    rather than repetition.
    frames += [ball(shake=0), ball(shake=0)]
    for shake in (1, -1, 1, -1, 0):
        frames.append(ball(shake=shake))

    # 2. It splits open along the seam, one row at a time so the split is legible
    #    rather than a single jump.
    for amount in (1, 2, 3, 4):
        frames.append(ball(open_amount=amount))

    # 3. The Pokemon fades up out of the opened ball.
    for f in (0.15, 0.35, 0.6, 0.85, 1.0):
        frames.append(scale_palette(sprite_blob, f))

    # 4. Hold on the finished article before the loop restarts.
    frames += [sprite_blob] * 5

    return [banner_text(b, pid) for b in frames], 110


def shift_sprite(blob, rows):
    """Return `blob` with `rows` blank PIXEL rows added at the top.

    Shifting happens in the sprite data, before anything is composed, so the
    whole Pokemon moves as one. An earlier version tried to split the rendered
    banner into sprite/info columns and move the left half -- that broke as soon
    as the banner grew a full-width header line, because the split point was
    inferred from the widest text gap and landed mid-sprite. Only part of Pikachu
    bobbed. Operating on pixels instead has no such coupling.
    """
    if rows <= 0:
        return blob
    out = dict(blob)
    out["h"] = blob["h"] + rows
    out["px"] = ("0" * (blob["w"] * rows)) + blob["px"]
    return out


def _compose_fixed(art_rows, info_rows, gap=3):
    """Lay out art beside an info column WITHOUT collapsing blank rows.

    banner.compose() cannot be reused for animation. It drops any fully-blank
    output line, so blank rows padded above a sprite -- exactly the mechanism that
    makes it sit lower in the frame -- are discarded and the art never moves. It
    also vertically centres the info against the sprite's height, so any change in
    art height drags the labels along.

    This keeps every row, and pins the info block to a fixed offset, so the only
    thing that moves between frames is the Pokemon.
    """
    art_w = max((len(_vis(r)) for r in art_rows), default=0)
    height = max(len(art_rows), len(info_rows))
    out = []
    for i in range(height):
        left = art_rows[i] if i < len(art_rows) else ""
        right = info_rows[i] if i < len(info_rows) else ""
        pad = " " * max(0, art_w - len(_vis(left)))
        out.append((left + pad + " " * gap + right).rstrip())
    return "\n".join(out)


def _vis(s):
    import re as _re

    return _re.sub(r"\x1b\[[0-9;]*m", "", s)


def _info_block(pid, is_new=True, dup=1):
    """The banner's right-hand text column, rebuilt so it can be placed exactly."""
    from pokeclaude import encounter

    info = META[str(pid)]
    accent = banner.GOLD if is_new else banner.SILVER
    tier = encounter.rarity_tier(pid)
    share = encounter.encounter_share(pid, ROSTER)
    share_txt = (
        ("%.3f" % share).rstrip("0").rstrip(".") if share < 0.1 else "%.2f" % share
    )
    tint = banner.GOLD if tier in ("MYTHICAL", "LEGENDARY") else banner.SILVER
    status = (
        banner._c(banner.GOLD, "NEW", bold=True)
        + " "
        + banner._c(banner.GOLD, "— added to your Pokedex")
        if is_new
        else banner._c(banner.SILVER, "duplicate ×%d" % dup)
    )
    return [
        "%s  %s"
        % (banner._c(accent, "#%03d" % pid), banner._types(info["types"])),
        status,
        banner.DIM
        + "%s%% of encounters" % share_txt
        + banner.RESET
        + "  "
        + banner._c(tint, tier, bold=tier in ("MYTHICAL", "LEGENDARY")),
        "",
        banner.DIM + "Pokedex 1/%d (0%%)" % len(ROSTER) + banner.RESET,
        banner.DIM + "/pokeclaude:pokedex to browse" + banner.RESET,
    ]


def frames_bob(pid, travel=2, cycle=None):
    """Idle mascot: the whole sprite rises and settles, looping.

    Every frame is the same height and the info column sits at a fixed row, so the
    only thing that moves is the Pokemon -- as a single unit, which an earlier
    column-splitting version failed to do (it inferred a split point from the
    widest text gap, which landed mid-sprite once the banner grew a header, so
    only the left 13 columns of Pikachu bobbed).
    """
    base = spritelib.downscale(load(pid), 2)
    info = _info_block(pid)
    header = banner._c(banner.GOLD, "✦ ") + banner._c(
        banner.GOLD, "A wild %s appeared!" % META[str(pid)]["name"].upper(), bold=True
    )
    art = spritelib.render(base, indent=1)
    cycle = cycle or [0, 0, 1, travel, 1, 0]

    # Vertically centre the info once, against the CONSTANT full frame height.
    frame_h = len(art) + travel
    off = max(0, (frame_h - len(info)) // 2)
    info_rows = [""] * off + info

    out = []
    for lift in cycle:
        above = travel - lift
        rows = [""] * above + art + [""] * lift
        out.append(header + "\n\n" + _compose_fixed(rows, info_rows))
    return out, 150


def frames_sparkle(pid):
    """Shiny sweep: a brightness pulse crosses the sprite, for rare catches."""
    blob = load(pid)
    out = [banner_text(blob, pid)]
    for add in (40, 90, 140, 90, 40):
        out.append(banner_text(brighten(blob, add), pid))
    out += [banner_text(blob, pid)] * 4
    return out, 110


STYLES = {
    "reveal": frames_reveal,
    "ball": frames_ball,
    "bob": frames_bob,
    "sparkle": frames_sparkle,
}


def render_gif(texts, delay_ms, out_path, zoom=2):
    """Rasterise each ANSI frame to PNG and mux into a looping GIF.

    Frames are padded to a common size so a shorter frame (the bob shift trims a
    row) does not resize the GIF canvas mid-loop.
    """
    tmp = tempfile.mkdtemp(prefix="pokeanim-")
    pngs = []
    for i, text in enumerate(texts):
        svg = a2s.to_svg(a2s.parse(text.strip("\n")))
        sp = os.path.join(tmp, "f%02d.svg" % i)
        pp = os.path.join(tmp, "f%02d.png" % i)
        with open(sp, "w") as f:
            f.write(svg)
        subprocess.run(
            ["rsvg-convert", "-z", str(zoom), sp, "-o", pp], check=True
        )
        pngs.append(pp)

    imgs = [Image.open(p).convert("RGBA") for p in pngs]
    w = max(im.width for im in imgs)
    h = max(im.height for im in imgs)
    canvas = []
    for im in imgs:
        bg = Image.new("RGBA", (w, h), (13, 17, 23, 255))
        bg.alpha_composite(im, (0, 0))
        canvas.append(bg.convert("P", palette=Image.ADAPTIVE, colors=256))

    canvas[0].save(
        out_path, save_all=True, append_images=canvas[1:], duration=delay_ms,
        loop=0, disposal=2, optimize=True,
    )
    return w, h, len(canvas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--style", choices=sorted(STYLES), required=True)
    ap.add_argument("--id", type=int, default=143)
    ap.add_argument("--zoom", type=float, default=2.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    texts, delay = STYLES[args.style](args.id)
    out = os.path.join(REPO, args.out) if not os.path.isabs(args.out) else args.out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    w, h, n = render_gif(texts, delay, out, zoom=args.zoom)
    sys.stderr.write(
        "wrote %s (%.1f KB, %d frames, %dx%d)\n"
        % (args.out, os.path.getsize(out) / 1024.0, n, w, h)
    )


if __name__ == "__main__":
    sys.exit(main())
