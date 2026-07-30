"""Catch banner composition.

Emitted as a hook `systemMessage`. Verified against Claude Code 2.1.220: the
delivered attachment preserves newlines, raw truecolour SGR escapes and Unicode
half-blocks, and the UI paints them, so a banner can be real pixel art rather
than plain text.

Sprite lines are placed beside a text column so the banner stays visually
compact -- roughly 16 rows for a 32x32 sprite instead of sprite-then-caption
stacked vertically.
"""
import re

from . import sprite as spritelib

# Visible width has to be measured with escapes stripped; len() counts them.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

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
# A brighter, cooler gold for the shiny marker, so it reads as distinct from the
# ordinary GOLD accent rather than blending into it.
SHINY = (255, 236, 140)


def _c(rgb, text, bold=False):
    return "%s\033[38;2;%d;%d;%dm%s%s" % (
        BOLD if bold else "", rgb[0], rgb[1], rgb[2], text, RESET
    )


def _types(type_names):
    return " ".join(
        _c(TYPE_RGB.get(t, (150, 150, 150)), t.upper()) for t in type_names
    )


def compose(blob, name, dex_id, type_names, is_new, dup_count, unique, roster_size,
            width=80, roster_ids=None, shiny=False):
    """Build the banner string for a catch.

    Sprites are stored at 64px, which is wider than the info column can sit
    beside on an 80-column terminal, so the art is halved unless there is room
    for it at full size. Wrapping would shred the pixel art entirely.

    The fit test measures the info column rather than assuming its width, so
    adding a longer line here can never silently reintroduce wrapping.
    """
    # A shiny always gets the gold accent, even as a duplicate. A duplicate shiny
    # is still a 1-in-64 event and should not be dressed as the silver
    # "you already have this" case.
    accent = GOLD if (is_new or shiny) else SILVER

    title = "A wild %s%s appeared!" % ("SHINY " if shiny else "", name.upper())
    if is_new:
        status = _c(GOLD, "NEW", bold=True) + " " + _c(GOLD, "— added to your Pokedex")
    else:
        status = _c(SILVER, "duplicate ×%d" % dup_count)
    # Shininess gets its OWN line, not a suffix on the status. The two are
    # independent facts -- a shiny duplicate has to show both -- and `info` is a
    # list of rows laid out beside the sprite, so a "\n" inside one entry would
    # desync every row below it from the art.
    shiny_line = ""
    if shiny:
        from . import encounter

        odds = int(round(1.0 / encounter.SHINY_CHANCE))
        shiny_line = (
            _c(SHINY, "✧ SHINY", bold=True) + DIM + "  1 in %d" % odds + RESET
        )

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

    # The title leads the whole banner as its own text line, not as the first
    # line of the info column. This banner is emitted by the Stop hook, and
    # Claude Code prepends "Stop says:" while eating the leading newline -- so
    # whatever is on line 0 lands beside that label. Line 0 used to be the
    # sprite's top row, which got shunted sideways (same failure the detail view
    # hit with "PostToolUse:Bash says:"). A text header takes the hit instead,
    # and reads as a headline while doing it. It is removed from `info` so the
    # title is not shown twice.
    header = _c(accent, "✦ ") + _c(accent, title, bold=True)

    info = [
        "%s  %s" % (_c(accent, "#%03d" % dex_id), _types(type_names)),
        status,
    ]
    if shiny_line:
        info.append(shiny_line)
    info += [
        rarity,
        "",
        DIM + "Pokedex %d/%d (%.0f%%)" % (unique, roster_size, pct) + RESET,
        DIM + "/pokeclaude:pokedex to browse" + RESET,
    ]

    # Halve the art only if it genuinely does not fit beside the info column.
    #
    # The info width is MEASURED, not assumed. It used to be a hardcoded 34,
    # which was the widest line back when the longest was "/pokeclaude:pokedex
    # to browse". The rarity line ("0.013% of encounters  LEGENDARY") is longer
    # than that, so a wide sprite plus a rare species overflowed 80 columns and
    # wrapped -- shredding exactly the art the guard exists to protect.
    gap = 3
    info_w = max(len(_ANSI.sub("", line)) for line in info)
    if spritelib.visible_width(blob) + 1 + gap + info_w > width:
        blob = spritelib.downscale(blob, 2)
    art = spritelib.render(blob, indent=1)
    art_w = spritelib.visible_width(blob) + 1

    # On a genuinely narrow terminal the info column alone can be most of the
    # width, so even halved art has nowhere to sit beside it. Stack instead of
    # letting the two columns collide: taller, but nothing wraps.
    if art_w + gap + info_w > width:
        out = [header, ""] + art + [""] + info
        return "\n".join(l for l in out if l.strip()) or " "

    # Interleave: sprite on the left, info column on the right, vertically
    # centred against the sprite so short info blocks do not sit at the top.
    pad = " " * (art_w + gap)
    rows = max(len(art), len(info))
    off = max(0, (len(art) - len(info)) // 2)

    body = []
    for i in range(rows):
        left = art[i] if i < len(art) else " " * art_w
        j = i - off
        right = info[j] if 0 <= j < len(info) else ""
        line = (left + " " * gap + right).rstrip() if right else left.rstrip()
        if line.strip():  # drop fully-blank rows, as before, so art stays tight
            body.append(line)

    # Header on its own line, then a blank, then the sprite+info block. The blank
    # keeps the label clear of the art even after the harness eats one newline.
    return "\n".join([header, ""] + body) if body else pad
