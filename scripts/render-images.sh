#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
out="$root/docs/images"
build="$(mktemp -d)"
trap 'rm -rf "$build"' EXIT
chrome="${CHROME_PATH:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

shoot() {
  local scheme="$1" size="$2" target="$3" page="$4"
  "$chrome" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
    --allow-file-access-from-files --virtual-time-budget=6000 \
    --blink-settings=preferredColorScheme="$scheme" --window-size="$size" \
    --screenshot="$target" "$page" >/dev/null 2>&1
  echo "wrote ${target#"$root"/}"
}

mkdir -p "$out"
uv run --project "$root" skaldr "$root/examples/sales-pipeline.yaml" -o "$build/sales.html"
uv run --project "$root" skaldr "$root/data/example.yaml" -o "$build/warehouse.html"

shoot 1 1280,900 "$out/sales-light.png" "file://$build/sales.html"
shoot 0 1280,900 "$out/warehouse-dark.png" "file://$build/warehouse.html"
shoot 1 1600,820 "$out/hero.png" "file://$root/scripts/images/frames.html#hero"
shoot 1 1280,640 "$out/social.png" "file://$root/scripts/images/frames.html#social"
