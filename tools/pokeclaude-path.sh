#!/usr/bin/env sh
# Print the PokeClaude repo root, or nothing if it cannot be found.
#
# Skills invoked from a chat sidebar get no plugin-root variable, so they need a
# way to locate the repo that does not depend on the host.
for d in \
  "$POKECLAUDE_ROOT" \
  "$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)" \
  "$PWD" \
  "$HOME/pokeclaude" \
  "$HOME/proj/pokeclaude" \
  "$HOME/src/pokeclaude" \
  "$HOME/code/pokeclaude"
do
  [ -n "$d" ] && [ -f "$d/plugin/scripts/pokedex.py" ] && { printf '%s\n' "$d"; exit 0; }
done
exit 1
