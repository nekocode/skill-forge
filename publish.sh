#!/usr/bin/env bash
# Publish @nekocode/skill-forge to npm.
set -euo pipefail
cd "$(dirname "$0")/cli"

version=$(node -p "require('./package.json').version")

# prepublishOnly hook handles build + test automatically
npm publish --access=public --auth-type=web

echo "Published @nekocode/skill-forge@$version"
