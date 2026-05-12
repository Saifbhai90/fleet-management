"""Verify Firebase Admin SDK can initialize from local service account file (no secrets printed)."""
import glob
import json
import os
import sys

import firebase_admin
from firebase_admin import credentials


def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    candidates = [os.path.join(root, "firebase-service-account.json")]
    candidates.extend(
        sorted(glob.glob(os.path.join(root, "New folder", "*firebase-adminsdk*.json")))
    )
    path = next((p for p in candidates if os.path.isfile(p)), None)
    if not path:
        print("FAIL: no service account JSON found.")
        print("      Expected: firebase-service-account.json (project root)")
        print("      or: New folder/*firebase-adminsdk*.json")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    pid = d.get("project_id", "")
    email = d.get("client_email", "")
    if not pid or not email:
        print("FAIL: invalid service account JSON")
        sys.exit(1)
    cred = credentials.Certificate(path)
    app = firebase_admin.initialize_app(cred)
    print("OK: Firebase Admin SDK initialized")
    print("OK: project_id:", pid)
    local = email.split("@")[0]
    print("OK: client_email:", local[:6] + "..." + "@" + email.split("@", 1)[1])
    print("OK: credential file:", os.path.relpath(path, root))
    firebase_admin.delete_app(app)


if __name__ == "__main__":
    main()
