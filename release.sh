#!/usr/bin/env bash
# Create GitHub release with plugin tarball for project-embed sync.
# Packs only embed-relevant files: commands/, skills/, hooks/
# Usage: ./release.sh [--draft]

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

PLUGIN_FILE="$ROOT/.claude-plugin/plugin.json"
VERSION=$(grep -o '"version": "[^"]*"' "$PLUGIN_FILE" | head -1 | sed 's/"version": "//;s/"//')
TAG="v$VERSION"
TARBALL="skill-forge-$VERSION.tar.gz"

echo "Plugin version: $VERSION"
echo "Tag: $TAG"

# Check for uncommitted changes
if ! git diff --quiet HEAD; then
  echo "Error: uncommitted changes. Commit or stash first." >&2
  exit 1
fi

# Check tag doesn't already exist
if git rev-parse "$TAG" >/dev/null 2>&1; then
  echo "Error: tag $TAG already exists." >&2
  exit 1
fi

# Build tarball with embed-relevant files only
echo "Building tarball..."
tar czf "$TARBALL" -C "$ROOT" \
  commands/ \
  skills/ \
  hooks/

echo "  Created: $TARBALL"

# Parse flags
DRAFT_FLAG=""
if [[ "${1:-}" == "--draft" ]]; then
  DRAFT_FLAG="--draft"
fi

# Tag and release
git tag "$TAG"
echo "  Tagged: $TAG"

gh release create "$TAG" "$TARBALL" \
  --title "skill-forge $VERSION" \
  --notes "Plugin release $VERSION for project-embed sync." \
  $DRAFT_FLAG

rm -f "$TARBALL"
echo "Done. Release: $TAG"
