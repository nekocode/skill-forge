#!/usr/bin/env bash
# Bump plugin and/or CLI versions independently.
# Usage:
#   ./bump-version.sh                         # interactive
#   ./bump-version.sh --plugin <ver>          # plugin only
#   ./bump-version.sh --cli <ver>             # CLI only
#   ./bump-version.sh --plugin <ver> --cli <ver>

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

PLUGIN_JSON="$ROOT/.claude-plugin/plugin.json"
MARKETPLACE_JSON="$ROOT/.claude-plugin/marketplace.json"
CLI_PACKAGE_JSON="$ROOT/cli/package.json"

# Validate semver format
validate_semver() {
  local ver="$1"
  if [[ ! "$ver" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$ ]]; then
    echo "Error: invalid semver — $ver" >&2
    exit 1
  fi
}

# Read current versions
CURRENT_PLUGIN=$(grep -o '"version": "[^"]*"' "$PLUGIN_JSON" | head -1 | sed 's/"version": "//;s/"//')
CURRENT_CLI=$(grep -o '"version": "[^"]*"' "$CLI_PACKAGE_JSON" | head -1 | sed 's/"version": "//;s/"//')

printf "Current plugin version: %s\n" "$CURRENT_PLUGIN"
printf "Current CLI version:    %s\n" "$CURRENT_CLI"
echo ""

# Parse flags
NEW_PLUGIN=""
NEW_CLI=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --plugin)
      NEW_PLUGIN="${2:-}"
      shift 2
      ;;
    --cli)
      NEW_CLI="${2:-}"
      shift 2
      ;;
    *)
      echo "Error: unknown argument — $1" >&2
      exit 1
      ;;
  esac
done

# Interactive mode if no flags given
if [[ -z "$NEW_PLUGIN" && -z "$NEW_CLI" ]]; then
  printf "New plugin version (enter to skip): "
  read -r NEW_PLUGIN
  printf "New CLI version (enter to skip): "
  read -r NEW_CLI
fi

# Validate non-empty inputs
[[ -n "$NEW_PLUGIN" ]] && validate_semver "$NEW_PLUGIN"
[[ -n "$NEW_CLI" ]] && validate_semver "$NEW_CLI"

# Nothing to do
if [[ -z "$NEW_PLUGIN" && -z "$NEW_CLI" ]]; then
  echo "Nothing to bump."
  exit 0
fi

DID_SOMETHING=0

# Bump plugin version → plugin.json + marketplace.json
if [[ -n "$NEW_PLUGIN" ]]; then
  if [[ "$NEW_PLUGIN" == "$CURRENT_PLUGIN" ]]; then
    echo "  Plugin version unchanged."
  else
    ESC="${CURRENT_PLUGIN//./\\.}"
    sed -i '' "s/\"version\": \"$ESC\"/\"version\": \"$NEW_PLUGIN\"/" "$PLUGIN_JSON"
    sed -i '' "s/\"version\": \"$ESC\"/\"version\": \"$NEW_PLUGIN\"/" "$MARKETPLACE_JSON"
    echo "  Updated: .claude-plugin/plugin.json → $NEW_PLUGIN"
    echo "  Updated: .claude-plugin/marketplace.json → $NEW_PLUGIN"
    DID_SOMETHING=1
  fi
else
  echo "  Plugin version skipped."
fi

# Bump CLI version → cli/package.json + package-lock.json sync
if [[ -n "$NEW_CLI" ]]; then
  if [[ "$NEW_CLI" == "$CURRENT_CLI" ]]; then
    echo "  CLI version unchanged."
  else
    ESC="${CURRENT_CLI//./\\.}"
    sed -i '' "s/\"version\": \"$ESC\"/\"version\": \"$NEW_CLI\"/" "$CLI_PACKAGE_JSON"
    echo "  Updated: cli/package.json → $NEW_CLI"
    (cd "$ROOT/cli" && npm install --package-lock-only --ignore-scripts 2>/dev/null)
    echo "  Updated: cli/package-lock.json"
    DID_SOMETHING=1
  fi
else
  echo "  CLI version skipped."
fi

if [[ $DID_SOMETHING -eq 1 ]]; then
  echo "Done."
fi
