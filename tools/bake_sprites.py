#!/usr/bin/env python3
"""Bake official Pokemon PNGs into pokeclaude's compact sprite format.

Source art is 96x96 with a hard alpha edge and very few colours (typically
10-16). Naive downscaling wrecks both properties: bilinear filtering smears
semi-transparent fringe pixels around the silhouette, and it invents hundreds of
intermediate colours that then have to be quantized back down anyway.

So the resize is done in two explicit passes:

  1. Alpha is thresholded to a hard mask and downscaled with NEAREST, keeping
     the silhouette crisp (no 1px halo of ghost pixels).
  2. Colour is downscaled with BOX averaging for smooth interior shading, then
     re-quantized to <=15 opaque entries so it fits a nibble per pixel.

Pixels the mask calls transparent get index 0 regardless of what the colour
pass produced, which is what keeps edges clean.

Usage:
    python3 tools/bake_sprites.py --max-dex 386 --size 32
    python3 tools/bake_sprites.py --ids 25,133,6 --size 32 --preview
"""
import argparse
import json
import os
import sys
import time
import urllib.request

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow required: pip3 install Pillow")

SPRITE_URL = (
    "https://raw.githubusercontent.com/PokeAPI/sprites/master"
    "/sprites/pokemon/{id}.png"
)
# Shiny art lives under the same tree with a shiny/ prefix, in the identical
# 96x96 format, so it bakes through exactly the same pipeline.
SHINY_URL = (
    "https://raw.githubusercontent.com/PokeAPI/sprites/master"
    "/sprites/pokemon/shiny/{id}.png"
)
SPECIES_URL = "https://pokeapi.co/api/v2/pokemon/{id}/"

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "plugin", "assets", "sprites")
META_PATH = os.path.join(REPO, "plugin", "assets", "pokemon.json")
CACHE = os.path.join(REPO, ".cache", "png")

MAX_PALETTE = 63  # index 0 reserved for transparent; base64-ish digit per pixel
ALPHA_CUTOFF = 128

# PokeAPI names the DEFAULT form with a disambiguating suffix -- "deoxys-normal",
# "darmanitan-standard", "squawkabilly-green-plumage". We only ever bake the
# default form's art, so the suffix labels nothing and reads as noise in a
# Pokedex; "squawkabilly-green-plumage" is also 26 characters, which overflows a
# grid cell and gets truncated mid-word.
#
# This is a denylist of known form suffixes rather than "cut at the first hyphen"
# on purpose: 39 species have a hyphen as a genuine part of the name, and the
# naive rule would turn iron-treads into "iron", tapu-koko into "tapu" and ho-oh
# into "ho".
FORM_SUFFIXES = (
    "normal", "plant", "altered", "land", "red-striped", "standard", "male",
    "incarnate", "ordinary", "aria", "shield", "average", "50", "baile",
    "midday", "solo", "red-meteor", "disguised", "amped", "ice", "full-belly",
    "single-strike", "green-plumage", "zero", "curly", "two-segment",
    "family-of-four",
)


def display_name(name):
    """Strip a default-form suffix, leaving the name people actually recognise."""
    for suffix in sorted(FORM_SUFFIXES, key=len, reverse=True):
        if name.endswith("-" + suffix):
            return name[: -(len(suffix) + 1)]
    return name


# Pixel indices are one character each. With a palette above 16 entries a single
# hex digit is not enough, so use a 64-symbol alphabet: same one-char-per-pixel
# density, four times the colour depth.
_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ+-"


def _enc(i):
    return _ALPHABET[i]


def fetch(url, dest, retries=3):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pokeclaude"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read()
            with open(dest, "wb") as f:
                f.write(data)
            return dest
        except Exception as e:  # transient network / rate limit
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("fetch failed %s: %s" % (url, last))


def bake_one(png_path, size):
    """Return a baked sprite dict, or None if the image is effectively empty."""
    im = Image.open(png_path).convert("RGBA")

    # Official art sits in a 96x96 frame with generous transparent margins.
    # Crop to the drawn content first, otherwise a third of our pixel budget is
    # spent encoding empty space and the sprite reads as tiny and mushy.
    alpha = im.getchannel("A").point(lambda a: 255 if a >= ALPHA_CUTOFF else 0)
    bbox = alpha.getbbox()
    if bbox is None:
        return None
    im, alpha = im.crop(bbox), alpha.crop(bbox)

    # Fit the cropped art into a size x size box, preserving aspect ratio so
    # tall Pokemon stay tall. Scaled dims are computed once and shared by both
    # passes below.
    cw, ch = im.size
    scale = float(size) / max(cw, ch)
    tw, th = max(1, int(round(cw * scale))), max(1, int(round(ch * scale)))
    ox, oy = (size - tw) // 2, size - th  # centre horizontally, sit on floor

    # Pass 1 -- hard silhouette. Threshold before downscaling so averaging can
    # never introduce partially-transparent halo pixels around the edge.
    mask = Image.new("L", (size, size), 0)
    mask.paste(alpha.resize((tw, th), Image.NEAREST), (ox, oy))

    # Pass 2 -- interior colour. Flatten using the hard mask so transparent
    # regions contribute nothing to the box average.
    cropped = Image.new("RGBA", im.size, (0, 0, 0, 0))
    cropped.paste(im, (0, 0), alpha)
    rgb = Image.new("RGB", (size, size), (0, 0, 0))
    rgb.paste(cropped.convert("RGB").resize((tw, th), Image.BOX), (ox, oy))

    # Quantize only the pixels we will actually draw.
    quant = rgb.quantize(colors=MAX_PALETTE, method=Image.MEDIANCUT, dither=Image.NONE)
    pal_raw = quant.getpalette()[: MAX_PALETTE * 3]
    palette = [
        tuple(pal_raw[i * 3 : i * 3 + 3]) for i in range(MAX_PALETTE)
    ]

    qpx = list(quant.getdata())
    mpx = list(mask.getdata())

    # Remap to a dense palette containing only colours that survive the mask.
    used, remap, out_pal = {}, {}, []
    indices = []
    for i in range(size * size):
        if mpx[i] < ALPHA_CUTOFF:
            indices.append(0)
            continue
        q = qpx[i]
        if q not in remap:
            out_pal.append(palette[q])
            remap[q] = len(out_pal)  # 1-based; 0 is transparent
        used[q] = used.get(q, 0) + 1
        indices.append(remap[q])

    if not out_pal:
        return None
    if len(out_pal) > MAX_PALETTE:
        raise AssertionError("palette overflow: %d" % len(out_pal))

    # Trim fully transparent rows. The square canvas is only a layout device;
    # keeping its blank padding would roughly double every wide sprite's file
    # for no visual gain, and the renderer trims columns already.
    rows = [indices[y * size:(y + 1) * size] for y in range(size)]
    keep = [y for y, r in enumerate(rows) if any(v != 0 for v in r)]
    if not keep:
        return None
    rows = rows[keep[0]:keep[-1] + 1]
    return {
        "w": size,
        "h": len(rows),
        "pal": ["%02x%02x%02x" % c for c in out_pal],
        "px": "".join(_enc(i) for r in rows for i in r),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-dex", type=int, default=386)
    ap.add_argument("--ids", type=str, default=None, help="comma list, overrides range")
    ap.add_argument("--size", type=int, default=64)
    ap.add_argument("--preview", action="store_true", help="print sprites as rendered")
    ap.add_argument(
        "--shiny",
        action="store_true",
        help="bake the shiny variants into assets/sprites/shiny/ instead",
    )
    args = ap.parse_args()

    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
    else:
        ids = list(range(1, args.max_dex + 1))

    # Shiny art is a parallel tree of the same ids, so it reuses every stage of
    # this pipeline and only the source URL and output directory change. Metadata
    # (name, types) is shared -- a shiny Pikachu is still Pikachu.
    src_url = SHINY_URL if args.shiny else SPRITE_URL
    out_dir = os.path.join(OUT_DIR, "shiny") if args.shiny else OUT_DIR
    cache_dir = os.path.join(CACHE, "shiny") if args.shiny else CACHE

    os.makedirs(out_dir, exist_ok=True)
    meta = {}
    if os.path.exists(META_PATH):
        with open(META_PATH) as f:
            meta = json.load(f)

    failures = []
    for n, pid in enumerate(ids, 1):
        try:
            png = fetch(
                src_url.format(id=pid), os.path.join(cache_dir, "%d.png" % pid)
            )
            blob = bake_one(png, args.size)
            if blob is None:
                failures.append((pid, "empty sprite"))
                continue
            blob["id"] = pid

            if str(pid) not in meta:
                info = json.loads(
                    urllib.request.urlopen(
                        urllib.request.Request(
                            SPECIES_URL.format(id=pid),
                            headers={"User-Agent": "pokeclaude"},
                        ),
                        timeout=20,
                    ).read()
                )
                meta[str(pid)] = {
                    "name": display_name(info["name"]),
                    "types": [t["type"]["name"] for t in info["types"]],
                }

            with open(os.path.join(out_dir, "%d.json" % pid), "w") as f:
                json.dump(blob, f, separators=(",", ":"))

            if args.preview:
                sys.path.insert(0, os.path.join(REPO, "plugin", "lib"))
                from pokeclaude import sprite

                print("\n#%03d %s (%d colours)" % (
                    pid, meta[str(pid)]["name"], len(blob["pal"])))
                for line in sprite.render(blob, indent=2):
                    print(line)

            if n % 25 == 0 or n == len(ids):
                sys.stderr.write("baked %d/%d\n" % (n, len(ids)))
        except Exception as e:
            failures.append((pid, str(e)))

    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=0, sort_keys=True)

    baked = [p for p in os.listdir(out_dir) if p.endswith(".json")]
    total = sum(os.path.getsize(os.path.join(out_dir, p)) for p in baked)
    sys.stderr.write(
        "\ndone: %d %ssprites, %.1f KB total, %d failures\n"
        % (len(baked), "shiny " if args.shiny else "", total / 1024.0, len(failures))
    )
    for pid, err in failures[:10]:
        sys.stderr.write("  FAIL #%d: %s\n" % (pid, err))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
