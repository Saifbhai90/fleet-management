"""Unit checks for GET /api/cascade/<entity> adapter (Flask test client)."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault('SKIP_STARTUP_TASKS', '1')

from app import app  # noqa: E402


def test_cascade_unknown_entity_404():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['user'] = 'master'
        sess['username'] = 'master'
        sess['is_master'] = True
    resp = client.get('/api/cascade/not-a-real-entity?parent=1')
    assert resp.status_code == 404
    data = resp.get_json()
    assert data.get('error') == 'unknown_entity'


def test_cascade_projects_empty_parent():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['user'] = 'master'
        sess['username'] = 'master'
        sess['is_master'] = True
    resp = client.get('/api/cascade/projects?parent=0')
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_cascade_vehicles_empty_without_parent():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['user'] = 'master'
        sess['username'] = 'master'
        sess['is_master'] = True
    resp = client.get('/api/cascade/vehicles?parent=0')
    assert resp.status_code == 200
    assert resp.get_json() == []
