#!/usr/bin/env bash
set -euo pipefail

version="${1:?usage: sync-tap-formula.sh <skaldr version without the leading v>}"
: "${GH_TOKEN:?GH_TOKEN must hold a token that can push to alex-yanchenko/homebrew-tap}"

PACKAGING_SPEC="packaging==26.3"
TAP_NAME="alex-yanchenko/tap"
BREW_INSTALL_ATTEMPTS=3

for i in $(seq 1 30); do
  printf 'skaldr==%s\n' "$version" | uv pip compile - --python-version 3.13 --refresh --quiet >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && { echo "skaldr $version not resolvable on PyPI after 5 min"; exit 1; }
  sleep 10
done

tap=$(mktemp -d)
git clone --depth 1 "https://x-access-token:${GH_TOKEN}@github.com/alex-yanchenko/homebrew-tap" "$tap"

for i in $(seq 1 5); do
  uv run --no-project --with "$PACKAGING_SPEC" python "$tap/scripts/gen-skaldr-formula.py" "$version" > "$tap/Formula/skaldr.rb" && break
  [ "$i" -eq 5 ] && { echo "formula generation failed after 5 attempts"; exit 1; }
  sleep 15
done

cd "$tap"
git config user.name "alex-release-bot[bot]"
git config user.email "alex-release-bot[bot]@users.noreply.github.com"
if git diff --quiet; then
  echo "formula already at skaldr $version"
  exit 0
fi
git commit -am "chore: skaldr $version"

export HOMEBREW_NO_AUTO_UPDATE=1
brew tap "$TAP_NAME" "$tap"
for i in $(seq 1 "$BREW_INSTALL_ATTEMPTS"); do
  brew install "$TAP_NAME/skaldr" && break
  [ "$i" -eq "$BREW_INSTALL_ATTEMPTS" ] && { echo "brew install failed after $BREW_INSTALL_ATTEMPTS attempts"; exit 1; }
  sleep 30
done
brew test "$TAP_NAME/skaldr"
git push
