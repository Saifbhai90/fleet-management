import os
import sys

os.environ.setdefault('SKIP_STARTUP_TASKS', '1')
sys.path.insert(0, '.')
from app import app

with app.test_request_context('/'):
    ctx = {}
    for fn in app.template_context_processors[None]:
        ctx.update(fn())
    h = ctx.get('fleet_static_hash')
    for p in [
        'js/core/fleet_core.js',
        'js/core/fleet_ui.js',
        'js/core/fleet_mobile.js',
        'css/core/fleet_styles.css',
    ]:
        print(p, h(p) if h else None)
