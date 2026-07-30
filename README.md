# PokeClaude

Catch Pokemon while you work. Every turn you spend tokens in Claude Code is a chance at
a wild encounter, rendered as truecolor pixel art directly in your terminal.

```
   ▄▀▀▀▀▄        ✦ A wild SNORLAX appeared!
  ▀▀▀▀▀▀▀▀
  ▀▀▀▀▀▀▀▀       #143  NORMAL
   ▀▀▀▀▀▀        NEW — added to your Pokedex

                 Pokedex 1/386 (0%)
                 /pokedex to browse
```

Your Pokedex is shared across **every** Claude Code instance — parallel sessions, every
project, one collection.

## Install

```bash
claude plugin marketplace add /path/to/pokeclaude
claude plugin install pokeclaude@pokeclaude
```

Then start a new session and `/pokedex` to browse your collection. Catches begin
appearing as you work.

Requires Python 3 (system `python3` is fine) and a truecolor terminal.

Claude Code reports the footprint as **~26 tokens always-on** and classifies the hook as
`harness-only — no model context cost`; check it yourself with
`claude plugin details pokeclaude`.

## How it works

**Catch rolls.** A `Stop` hook fires once per completed turn, reads that turn's real
assistant `output_tokens` from the session transcript, and rolls against it. Long
grinding turns genuinely improve your odds; idle ones do nothing.

**Rate.** `TOKENS_PER_CATCH` is calibrated to roughly one catch per 45–60 minutes of
active work — measured against a median of ~1,100 output tokens/min across 157 real
sessions, giving ~53 min/catch. Raise it in
[`encounter.py`](plugin/lib/pokeclaude/encounter.py) for rarer catches, lower it for more.

One subtlety worth knowing if you retune it: Claude Code writes one transcript record per
content block and repeats the message's *final* `output_tokens` on every one, so naive
per-record summing over-counts by 2–3x. Always deduplicate by `message.id` when measuring.

**It costs you nothing.** The catch banner is delivered via a hook's `systemMessage`,
which Claude Code renders to the UI *without* injecting it into the model's context.
Measured: 24.5k tokens of banner content delivered across four catches produced a **+0**
change in input/cache tokens. Reading the transcript happens in a separate process, off
the model's context entirely. PokeClaude observes your token usage; it never adds to it.

**Duplicates.** Already-caught species stay possible but are deliberately rarer —
weighted at `DUPLICATE_WEIGHT` (0.25) of an unseen one. Early on almost every catch is
new; duplicates only dominate once the Pokedex is nearly full, so catches never dry up.

**Legendaries** carry their own rarity multipliers (Mewtwo is ~15x rarer than Pidgey).

## Commands

| Command | What it does |
|---|---|
| `/pokedex` | Paginated grid of everything you've caught |
| `/pokedex --all` | Include uncaught entries as dim silhouettes |
| `/pokedex --id 25` | Large detail view for one species |
| `/pokedex --stats` | Progress summary, no art |
| `/pokedex --dupes` | Full duplicate list, most-caught first |
| `/pokedex --project` | Only Pokemon caught while working in this project |
| `/pokedex --scale 1` | Full-size 32px sprites |
| `/pokeclaude-release <name>` | Release one Pokemon (dry-run first) |
| `/pokeclaude-release all` | Wipe the Pokedex and start over |

### Per-project Pokedex

`--project` scopes to the current repo (git toplevel, else the working directory), so you
can see how your luck has been on one project. Per-project counts are tracked
independently, not merely filtered — Pikachu can be ×4 globally while being ×3 here and
×1 somewhere else.

The global collection is always the source of truth. `--project` is a view over it, and
`/pokeclaude-release all --project` resets one project's records **without** touching your
real collection.

### Releasing

Releasing deletes collection data, so it is deliberately two-step: the command dry-runs
first, prints exactly what would be removed, and exits without changing anything until you
pass `--confirm`.

| Exit | Meaning |
|---|---|
| `0` | done, or nothing to do |
| `1` | unknown Pokemon, or lock unavailable (nothing changed) |
| `2` | dry run — awaiting `--confirm` |

## Rendering

Sprites are drawn with Unicode half-blocks (`▀`), where a glyph's foreground paints the
upper pixel and its background the lower one — two pixels per character cell, so a 32x32
sprite occupies 32 columns by 16 rows. Grid views downsample 2x to fit more per row, and
column count is derived from your actual terminal width because wrapping destroys pixel
art.

## Storage

Everything lives in `~/.claude/pokeclaude/`:

```
pokedex.json        your collection
pokedex.json.lock   O_EXCL mutex
state.json          per-session roll bookkeeping
```

Writes take a lockfile, re-read inside the lock, and swap in via atomic rename, so
parallel Claude sessions can't corrupt or clobber each other. Readers never block. A
corrupt file is quarantined as `.corrupt-<ts>` rather than overwritten.

Config via environment:

| Variable | Effect |
|---|---|
| `POKECLAUDE_DISABLE=1` | Turn off catching entirely |
| `POKECLAUDE_HOME` | Move the data directory (useful for testing) |
| `POKECLAUDE_WIDTH` | Override detected terminal width |

## Non-interference

The hook runs on every turn, so it is built to fail silently: unreadable transcript,
missing sprite, unavailable lock, malformed input — all exit 0 and print nothing. A
dropped catch is invisible. A crashing or hanging hook would ruin your session, so that
never happens.

Token accounting is single-spend: each assistant message's uuid is banked once, so
resumed or compacted sessions can't re-gamble tokens that were already rolled.

## Assets

Sprites are baked from [PokeAPI/sprites](https://github.com/PokeAPI/sprites) (official
96x96 art) into a compact palette+nibble format — ~1.2KB each, 450KB for all 386.

```bash
python3 tools/bake_sprites.py --max-dex 386 --size 32
python3 tools/bake_sprites.py --ids 25 --preview   # see one in your terminal
```

Baking crops to the content bbox before downscaling (otherwise a third of the pixel
budget encodes empty margin), thresholds alpha *before* resizing to keep silhouettes
crisp, and quantizes to <=15 colors so each pixel fits one nibble.

To extend past Gen 3, re-run with `--max-dex 1025`.

Pokemon is a trademark of Nintendo / Creatures Inc. / GAME FREAK Inc. This is an
unofficial fan project.
