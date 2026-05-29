#!/usr/bin/env sh
# Render build script — installs Python deps + Playwright Chromium binary.
# Used as buildCommand in render.yaml: sh scripts/render_build.sh
set -e

echo "=== Step 1: pip install ==="
pip install -r requirements.txt

echo "=== Step 2: playwright install chromium ==="
# Store browser binary inside project src so Render caches it between deploys.
# /opt/render/.cache is NOT reliably persisted — project dir IS cached by Render.
export PLAYWRIGHT_BROWSERS_PATH=/opt/render/project/src/.playwright-browsers
echo "Browser path: $PLAYWRIGHT_BROWSERS_PATH"
playwright install chromium
echo "=== Step 2b: install OS deps ==="
playwright install-deps chromium || echo "install-deps skipped (may need sudo on some envs)"

echo "=== Step 3: verify binary exists ==="
find "$PLAYWRIGHT_BROWSERS_PATH" -name "headless_shell" -o -name "chrome" 2>/dev/null | head -5 || echo "WARNING: binary not found after install!"

echo "=== Build complete ==="
