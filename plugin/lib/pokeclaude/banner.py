"""Catch banner composition.

Emitted as a hook `systemMessage`. Verified against Claude Code 2.1.220: the
delivered attachment preserves newlines, raw truecolour SGR escapes and Unicode
half-blocks, and the UI paints them, so a banner can be real pixel art rather
than plain text.

Sprite lines are placed beside a text column so the banner stays visually
compact -- roughly 16 rows for a 32x32 sprite instead of sprite-then-caption
stacked vertically.
"""
from . import sprite as spritelib

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"

# Type colours, eyeballed from the standard type chart.
TYPE_RGB = {
    "normal": (168, 168, 120), "fire": (240, 128, 48), "water": (104, 144, 240),
    "electric": (248, 208, 48), "grass": (120, 200, 80), "ice": (152, 216, 216),
    "fighting": (192, 48, 40), "poison": (160, 64, 160), "ground": (224, 192, 104),
    "flying": (168, 144, 240), "psychic": (248, 88, 136), "bug": (168, 184, 32),
    "rock": (184, 160, 56), "ghost": (112, 88, 152), "dragon": (112, 56, 248),
    "dark": (112, 88, 72), "steel": (184, 184, 208), "fairy": (238, 153, 172),
}
GOLD = (246, 200, 60)
SILVER = (170, 175, 185)


def _c(rgb, text, bold=False):
    return "%s\033[38;2;%d;%d;%dm%s%s" % (
        BOLD if bold else "", rgb[0], rgb[1], rgb[2], text, RESET
    )


def _types(type_names):
    return " ".join(
        _c(TYPE_RGB.get(t, (150, 150, 150)), t.upper()) for t in type_names
    )


def compose(blob, name, dex_id, type_names, is_new, dup_count, unique, roster_size,
            width=80, roster_ids=None):
    """Build the banner string for a catch.

    Sprites are stored at 64px, which is wider than the info column can sit
    beside on an 80-column terminal, so the art is halved unless there is room
    for it at full size. Wrapping would shred the pixel art entirely.
    """
    info_w = 34  # widest info line plus the gap
    if spritelib.visible_width(blob) + info_w > width:
        blob = spritelib.downscale(blob, 2)
    art = spritelib.render(blob, indent=1)
    accent = GOLD if is_new else SILVER

    title = "A wild %s appeared!" % name.upper()
    if is_new:
        status = _c(GOLD, "NEW", bold=True) + " " + _c(GOLD, "— added to your Pokedex")
    else:
        status = _c(SILVER, "duplicate ×%d" % dup_count)

    pct = (100.0 * unique / roster_size) if roster_size else 0.0
    rarity = ""
    if roster_ids:
        from . import encounter

        tier = encounter.rarity_tier(dex_id)
        share = encounter.encounter_share(dex_id, roster_ids)
        share_txt = ("%.3f" % share).rstrip("0").rstrip(".") if share < 0.1 else "%.2f" % share
        # Legendaries get the gold treatment; commons stay dim so the rare ones
        # actually stand out rather than every catch shouting.
        tint = GOLD if tier in ("MYTHICAL", "LEGENDARY") else SILVER
        rarity = DIM + "%s%% of encounters" % share_txt + RESET + "  " + _c(tint, tier, bold=tier in ("MYTHICAL", "LEGENDARY"))

    info = [
        "",
        _c(accent, "✦ ") + _c(accent, title, bold=True),
        "",
        "%s  %s" % (_c(accent, "#%03d" % dex_id), _types(type_names)),
        status,
        rarity,
        "",
        DIM + "Pokedex %d/%d (%.0f%%)" % (unique, roster_size, pct) + RESET,
        DIM + "/pokeclaude:pokedex to browse" + RESET,
    ]

    # Interleave: sprite on the left, info column on the right, vertically
    # centred against the sprite so short info blocks do not sit at the top.
    art_w = spritelib.visible_width(blob) + 1
    gap = 3
    pad = " " * (art_w + gap)
    rows = max(len(art), len(info))
    off = max(0, (len(art) - len(info)) // 2)

    out = []
    for i in range(rows):
        left = art[i] if i < len(art) else " " * art_w
        j = i - off
        right = info[j] if 0 <= j < len(info) else ""
        out.append((left + " " * gap + right).rstrip() if right else left.rstrip())
    return "\n".join(l for l in out if l.strip()) or pad
