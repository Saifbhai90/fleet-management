#!/usr/bin/env sh
# Use as Render "Pre-Deploy Command": scripts/render_migrate.sh
# Required env (Render → Web Service → Environment):
#   SECRET_KEY   — app.py fails to import without it
#   DATABASE_URL — PostgreSQL (Internal URL); sqlite on ephemeral disk is wrong for production
# Optional: FLASK_APP=app:app (this script sets a default)
set -e
cd "$(dirname "$0")/.." || exit 1
export FLASK_APP="${FLASK_APP:-app:app}"
if [ -z "$SECRET_KEY" ]; then
  echo "render_migrate: ERROR: SECRET_KEY is not set. Add it in Render → Environment."
  exit 1
fi
if [ -z "$DATABASE_URL" ]; then
  echo "render_migrate: ERROR: DATABASE_URL is not set. Link PostgreSQL and set Internal URL."
  exit 1
fi
# Helpful: show alembic target without secrets
if command -v python >/dev/null 2>&1; then
  python -c "import os; u=os.environ.get('DATABASE_URL',''); print('render_migrate: DB scheme =', (u.split(':',1)[0] if u else 'missing'))" || true
fi
exec python -m flask db upgrade
