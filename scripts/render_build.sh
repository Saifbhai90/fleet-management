#!/usr/bin/env sh
# Render build script — installs Python deps + Playwright Chromium binary.
# Used as buildCommand in render.yaml: sh scripts/render_build.sh
set -e

echo "=== Step 1: pip install ==="
pip install -r requirements.txt

echo "=== Step 2: playwright install chromium ==="
# Install Chromium browser binary + OS-level dependencies.
# PLAYWRIGHT_BROWSERS_PATH ensures binary lands in a known writable location.
export PLAYWRIGHT_BROWSERS_PATH=/opt/render/.cache/ms-playwright
playwright install chromium
playwright install-deps chromium

echo "=== Build complete ==="
