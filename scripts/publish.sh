#!/usr/bin/env bash
# Publish this repo to GitHub.
# Usage: bash scripts/publish.sh https://github.com/YOUR_USERNAME/client-finder-agent.git
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: bash scripts/publish.sh <github-repo-url>" >&2
  exit 1
fi

URL="$1"
cd "$(dirname "$0")/.."

git remote remove origin 2>/dev/null || true
git remote add origin "$URL"
git branch -M main
echo "Pushing to $URL ..."
git push -u origin main
echo "Done. Repository is live at ${URL%.git}"
