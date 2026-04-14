#!/usr/bin/env bash
# Bump version across plugin.json, marketplace.json, cli/package.json, cli/package-lock.json.
# Usage: ./bump-version.sh [new-version]

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

FILES=(
  "$ROOT/.claude-plugin/plugin.json"
  "$ROOT/.claude-plugin/marketplace.json"
  "$ROOT/cli/package.json"
)

# Read current version from plugin.json (single source of truth)
CURRENT=$(grep -o '"version": "[^"]*"' "$ROOT/.claude-plugin/plugin.json" | head -1 | sed 's/"version": "//;s/"//')

echo "Current version: $CURRENT"

if [[ $# -ge 1 ]]; then
  NEW="$1"
else
  printf "New version: "
  read -r NEW
fi

if [[ ! "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$ ]]; then
  echo "Error: invalid semver — $NEW" >&2
  exit 1
fi

if [[ "$NEW" == "$CURRENT" ]]; then
  echo "Version unchanged."
  exit 0
fi

# Escape dots for sed regex
CURRENT_ESC="${CURRENT//./\\.}"

for f in "${FILES[@]}"; do
  sed -i '' "s/\"version\": \"$CURRENT_ESC\"/\"version\": \"$NEW\"/" "$f"
  echo "  Updated: ${f#"$ROOT/"}"
done

# Sync package-lock.json
(cd "$ROOT/cli" && npm install --package-lock-only --ignore-scripts 2>/dev/null)
echo "  Updated: cli/package-lock.json"

echo "Done: $CURRENT -> $NEW"
