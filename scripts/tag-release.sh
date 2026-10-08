#!/usr/bin/env bash
# Run after committing the version bump, changelog, and verified changes.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
git diff --quiet HEAD -- || { echo 'Commit tracked changes first.' >&2; exit 1; }
version=$(PYTHONPATH=src python3 -c 'from shopping_bot import __version__; print(__version__)')
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Expected MAJOR.MINOR.PATCH'; exit 1; }
git tag -a "v$version" -m "Release $version"
echo "Created v$version. Push with: git push origin HEAD v$version"
