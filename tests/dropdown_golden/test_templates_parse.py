"""Parse every Jinja template in templates/ so syntax landmines never ship.

Regression guard for the `{#districtSelect}` bug (2026-09): a data-cascade-url
attribute contained `{#...}` which Jinja's lexer treats as a comment opener —
8 pages failed to render (500) and 2 pages silently swallowed ~228 lines of
markup. This check is pure jinja2 (no Flask boot, no database) so it runs
anywhere, fast.

Run standalone:  python tests/dropdown_golden/test_templates_parse.py
Or via pytest:   pytest tests/dropdown_golden/test_templates_parse.py
"""
import os

import jinja2

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
T = os.path.join(ROOT, 'templates')


def _template_files():
    found = []
    for root, _dirs, files in os.walk(T):
        for f in files:
            if f.endswith(('.html', '.jinja', '.j2')):
                found.append(os.path.join(root, f))
    return sorted(found)


def _parse_all():
    """Return a list of (path, error) for every template that fails to parse."""
    env = jinja2.Environment()
    failures = []
    for path in _template_files():
        try:
            with open(path, encoding='utf-8') as fh:
                env.parse(fh.read())
        except Exception as e:  # lexer/parser error = broken template
            failures.append((path, str(e)))
    return failures


def test_all_templates_parse_jinja():
    failures = _parse_all()
    if failures:
        msgs = '\n'.join('  %s -> %s' % (p, e) for p, e in failures)
        raise AssertionError(
            '%d template(s) have Jinja syntax errors:\n%s' % (len(failures), msgs)
        )


if __name__ == '__main__':
    failures = _parse_all()
    if failures:
        for p, e in failures:
            print('BROKEN:', p, '->', e)
        raise SystemExit('%d template(s) broken' % len(failures))
    print('OK: %d templates parse clean' % len(_template_files()))
