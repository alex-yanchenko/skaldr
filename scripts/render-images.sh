#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
out="$root/docs/images"
build="$(mktemp -d)"
trap 'rm -rf "$build"' EXIT
chrome="${CHROME_PATH:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

[ -x "$chrome" ] || { echo "Google Chrome not found at $chrome; set CHROME_PATH" >&2; exit 1; }
command -v uv >/dev/null || { echo "uv is required to render the samples" >&2; exit 1; }

frames="$build/frames"
mkdir -p "$frames"
cp "$root"/scripts/images/frames.{html,css,js} "$root/examples/sales-pipeline.yaml" "$frames/"

shoot() {
  local scheme="$1" size="$2" name="$3" page="$4"
  if ! "$chrome" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
    --allow-file-access-from-files --virtual-time-budget=6000 \
    --blink-settings=preferredColorScheme="$scheme" --window-size="$size" \
    --screenshot="$frames/$name" "$page" >"$build/chrome.log" 2>&1 || [ ! -s "$frames/$name" ]; then
    echo "Chrome did not write $name:" >&2
    cat "$build/chrome.log" >&2
    exit 1
  fi
}

uv run --project "$root" skaldr "$root/examples/sales-pipeline.yaml" -o "$build/sales.html"
uv run --project "$root" skaldr "$root/data/example.yaml" -o "$build/warehouse.html"

shoot 1 1280,900 sales-light.png "file://$build/sales.html"
shoot 0 1280,900 warehouse-dark.png "file://$build/warehouse.html"
shoot 1 1600,820 hero.png "file://$frames/frames.html#hero"
shoot 1 1280,640 social.png "file://$frames/frames.html#social"

mkdir -p "$out"
for name in sales-light.png warehouse-dark.png hero.png social.png; do
  cp "$frames/$name" "$out/$name"
  echo "wrote docs/images/$name"
done
