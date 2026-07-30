#!/usr/bin/env bash
# Regenerate every README image from the scripts' real output.
#
# The images are generated, never hand-drawn, so they cannot drift from what the
# code prints. Run this after any change to a sprite, a renderer, or the demo
# seed. It seeds a throwaway Pokedex in its own POKECLAUDE_HOME, so it never
# touches a real collection.
#
#   bash tools/regen_readme.sh
set -euo pipefail
cd "$(dirname "$0")/.."

DEMO="$(mktemp -d)/demodex"
mkdir -p "$DEMO"
python3 tools/seed_demo.py --home "$DEMO"

svg() { python3 tools/ansi_to_svg.py "$@"; }

svg --demo catch --id 143 --out docs/catch-snorlax.svg
svg --cmd "scripts/pokedex.py" --home "$DEMO" --width 100 --out docs/pokedex-page.svg
svg --cmd "scripts/pokedex.py --id 25"   --home "$DEMO" --out docs/detail-pikachu.svg
svg --cmd "scripts/pokedex.py --id 1007" --home "$DEMO" --out docs/detail-koraidon.svg
svg --cmd "scripts/pokedex.py --id 493"  --home "$DEMO" --out docs/detail-arceus-uncaught.svg

echo "regenerated 5 SVGs in docs/"
