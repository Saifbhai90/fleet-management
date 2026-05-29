#!/usr/bin/env sh
# Render build script — pip install + Playwright Chromium + Tesseract OCR
# NOTE: render.yaml buildCommand now uses inline env var approach.
# This script is kept as a reference / fallback.
set -e

echo "=== Step 1: pip install ==="
pip install -r requirements.txt

echo "=== Step 2: Playwright install chromium (relative path) ==="
export PLAYWRIGHT_BROWSERS_PATH=./.cache/ms-playwright
echo "PLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH"
python -m playwright install chromium
python -m playwright install-deps chromium || echo "install-deps: skipped (may need root)"

echo "=== Step 3: verify Chromium binary ==="
find "$PLAYWRIGHT_BROWSERS_PATH" \( -name "headless_shell" -o -name "chrome" \) 2>/dev/null | head -5 \
  || echo "WARNING: Chromium binary not found — browser launch will fail!"

echo "=== Step 4: system info ==="
free -m 2>/dev/null || echo "free: not available"
df -h /tmp 2>/dev/null || true

echo "=== Build complete ==="
