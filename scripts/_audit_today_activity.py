"""Audit today's activity for slow loads and errors."""
import sqlite3
from collections import defaultdict

TODAY = "2026-06-17"

c = sqlite3.connect("db/local.db")
c.row_factory = sqlite3.Row


def user_name(uid):
    r = c.execute(
        "SELECT full_name, username FROM user WHERE id=?", (uid,)
    ).fetchone()
    if not r:
        return f"User #{uid}"
    return (r["full_name"] or r["username"] or f"User #{uid}").strip()


print("=== DB activity_log range ===")
r = c.execute(
    "SELECT min(created_at) mn, max(created_at) mx, count(*) n FROM activity_log"
).fetchone()
print(dict(r))

print(f"\n=== TODAY ({TODAY}) summary ===")
r = c.execute(
    "SELECT count(*) n, count(DISTINCT user_id) users FROM activity_log WHERE date(created_at)=?",
    (TODAY,),
).fetchone()
print(f"Total hits: {r['n']}, distinct users: {r['users']}")

print("\n=== 404 / missing routes (endpoint NULL) ===")
rows = c.execute(
    """
    SELECT user_id, path, count(*) n, min(created_at) first_at, max(created_at) last_at
    FROM activity_log
    WHERE date(created_at)=? AND (endpoint IS NULL OR endpoint='')
    GROUP BY user_id, path ORDER BY n DESC
    """,
    (TODAY,),
).fetchall()
if not rows:
    print("  None")
for r in rows:
    print(f"  {user_name(r['user_id'])} | {r['path']} | x{r['n']} | {r['first_at']} .. {r['last_at']}")

print("\n=== Failed logins today ===")
rows = c.execute(
    """
    SELECT username, count(*) n FROM login_attempt
    WHERE date(created_at)=? AND success=0
    GROUP BY username ORDER BY n DESC LIMIT 15
    """,
    (TODAY,),
).fetchall()
if not rows:
    print("  None")
for r in rows:
    print(f"  {r['username']}: {r['n']} failed")

print("\n=== Rapid repeat same path (possible retry / stuck) ===")
rows = c.execute(
    """
    SELECT user_id, path, count(*) n
    FROM activity_log
    WHERE date(created_at)=? AND path NOT LIKE '/network-probe%'
    GROUP BY user_id, path HAVING n >= 8
    ORDER BY n DESC LIMIT 20
    """,
    (TODAY,),
).fetchall()
if not rows:
    print("  None notable")
for r in rows:
    print(f"  {user_name(r['user_id'])} | {r['path']} | {r['n']} hits")

print("\n=== Per-user session gaps (login without logout, long sessions) ===")
for r in c.execute(
    """
    SELECT ll.id, ll.user_id, ll.login_at, ll.logout_at, substr(ll.user_agent,1,70) ua
    FROM login_log ll
    WHERE date(ll.login_at)=?
    ORDER BY ll.login_at DESC LIMIT 25
    """,
    (TODAY,),
):
    d = dict(r)
    d["name"] = user_name(d["user_id"])
    print(d)

print("\n=== client activity_logs today ===")
cols = [x[1] for x in c.execute("PRAGMA table_info(activity_logs)")]
print("cols:", cols)
try:
    rows = c.execute(
        """
        SELECT user_id, action, count(*) n
        FROM activity_logs WHERE date(created_at)=?
        GROUP BY user_id, action ORDER BY n DESC LIMIT 30
        """,
        (TODAY,),
    ).fetchall()
    if not rows:
        print("  No client logs today (local DB)")
    for r in rows:
        print(f"  {user_name(r['user_id'])} | {r['action']} | x{r['n']}")
except Exception as e:
    print("  err:", e)

print("\n=== Top endpoints today ===")
for r in c.execute(
    """
    SELECT endpoint, count(*) n FROM activity_log
    WHERE date(created_at)=? AND endpoint IS NOT NULL
    GROUP BY endpoint ORDER BY n DESC LIMIT 15
    """,
    (TODAY,),
):
    print(f"  {r['endpoint']}: {r['n']}")
