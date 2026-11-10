#!/usr/bin/env bash
# Run ON the Mac, from a checkout: packaging/build-macos.sh
# Builds dist/track-glow/ for this Mac's CPU, smoke-tests it, and zips it to dist/track-glow-macos-<arch>.zip.
set -euo pipefail

[ "$(uname -s)" = "Darwin" ] || { echo "Run this on macOS." >&2; exit 1; }
major="$(sw_vers -productVersion | cut -d. -f1)"
[ "$major" -ge 14 ] || { echo "PySide6 6.12 needs macOS 14 or newer (this is $(sw_vers -productVersion))." >&2; exit 1; }
command -v uv >/dev/null || { echo "Install uv first: brew install uv  (or https://docs.astral.sh/uv/)" >&2; exit 1; }

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
arch="$(uname -m)"

uv sync --frozen --extra desktop
uv run pyinstaller packaging/track-glow.spec --noconfirm

exe=dist/track-glow/track-glow
"$exe" --version

port=18790
settings="$(mktemp -d)/settings.json"
TRACK_GLOW_CONFIG="$settings" "$exe" --headless --port "$port" >/dev/null 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
    curl -sf "http://127.0.0.1:$port/api/health" && break
    sleep 1
done
curl -sf "http://127.0.0.1:$port/api/health" >/dev/null || { echo "health check failed" >&2; exit 1; }
kill "$pid"
wait "$pid" 2>/dev/null || true

# Desktop mode proves Qt was bundled; the launcher binds 127.0.0.1:8780.
TRACK_GLOW_CONFIG="$settings" QT_QPA_PLATFORM=offscreen "$exe" >/dev/null 2>&1 &
pid=$!
for _ in $(seq 1 30); do
    curl -sf "http://127.0.0.1:8780/api/health" && break
    sleep 1
done
curl -sf "http://127.0.0.1:8780/api/health" >/dev/null || { echo "desktop mode failed: is Qt bundled?" >&2; exit 1; }
kill "$pid"

ditto -c -k --keepParent dist/track-glow "dist/track-glow-macos-$arch.zip"
echo "built: $root/dist/track-glow-macos-$arch.zip"
