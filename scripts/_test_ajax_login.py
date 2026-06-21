"""Quick check: POST /login?ajax=1 must return JSON."""
import json
import re
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

cj = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
html = opener.open("http://127.0.0.1:5050/login").read().decode()
m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
csrf = m.group(1) if m else ""
print("csrf len:", len(csrf))

data = urllib.parse.urlencode(
    {
        "username": "wronguser",
        "password": "wrongpass",
        "csrf_token": csrf,
        "_fleet_ajax": "1",
        "_fleet_bio_link": "1",
    }
).encode()
req = urllib.request.Request(
    "http://127.0.0.1:5050/login?ajax=1",
    data=data,
    method="POST",
    headers={
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
    },
)
resp = opener.open(req)
body = resp.read().decode()
print("Status:", resp.status)
print("Content-Type:", resp.headers.get("Content-Type"))
print("Body:", body[:300])
try:
    payload = json.loads(body)
    print("JSON ok:", payload.get("ok"), "error:", payload.get("error"))
except json.JSONDecodeError as exc:
    print("NOT JSON:", exc)
