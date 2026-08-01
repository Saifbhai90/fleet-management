#!/usr/bin/env sh
# Render initialDeployHook / manual: seed demo sample data when DEMO_MODE=1
set -e
cd "$(dirname "$0")/.." || exit 1
export FLASK_APP="${FLASK_APP:-app:app}"
if [ "${DEMO_MODE}" != "1" ] && [ "${DEMO_MODE}" != "true" ] && [ "${DEMO_MODE}" != "yes" ]; then
  echo "seed_demo: DEMO_MODE not enabled — skip"
  exit 0
fi
python -c "from services.demo_env import seed_demo_data; print(seed_demo_data())"
