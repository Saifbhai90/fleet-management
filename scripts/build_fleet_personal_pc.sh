#!/usr/bin/env bash
# Build daedalOS static export into Flask static/fleet_personal_pc (Linux/macOS/Render).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DAEDAL="${ROOT}/daedalOS"
DST="${ROOT}/static/fleet_personal_pc"

_export_node_from_tarball() {
  local ver="${NODE_DIST_VERSION:-20.18.1}"
  local arch="${NODE_DIST_ARCH:-linux-x64}"
  local base="node-v${ver}-${arch}"
  local url="https://nodejs.org/dist/v${ver}/${base}.tar.xz"
  local tmp="${ROOT}/.node-dist-cache"
  echo "[Fleet PC] Downloading Node ${ver} (${arch}) for build..."
  mkdir -p "${tmp}"
  curl -fsSL "${url}" -o "${tmp}/node.tar.xz"
  tar -xJf "${tmp}/node.tar.xz" -C "${tmp}"
  export PATH="${tmp}/${base}/bin:${PATH}"
}

if ! command -v node &>/dev/null; then
  if [[ "${BOOTSTRAP_NODE_FOR_BUILD:-0}" == "1" ]]; then
    _export_node_from_tarball
  fi
fi

if ! command -v node &>/dev/null; then
  echo "[Fleet PC] ERROR: Node.js is required. Options:"
  echo "  • Locally: install Node 20+, then re-run this script."
  echo "  • Render: set env BOOTSTRAP_NODE_FOR_BUILD=1 on your Web Service (uses NODE_DIST_VERSION optional)."
  exit 1
fi

echo "[Fleet PC] Using $(node -v) / $(npm -v)"

cd "${DAEDAL}"
export FLEET_OS_BASE_PATH="/static/fleet_personal_pc"
if [[ -f package-lock.json ]]; then
  npm ci --legacy-peer-deps
else
  npm install --legacy-peer-deps
fi
npm run build

mkdir -p "${DST}"
shopt -s dotglob nullglob
for item in "${DST}"/*; do
  [[ -e "${item}" ]] || continue
  base="$(basename "${item}")"
  [[ "${base}" == "README.txt" ]] && continue
  rm -rf "${item}"
done
shopt -u dotglob nullglob

cp -a "${DAEDAL}/out/"* "${DST}/"

echo "[Fleet PC] Done: ${DST}"
du -sh "${DST}" 2>/dev/null || true
