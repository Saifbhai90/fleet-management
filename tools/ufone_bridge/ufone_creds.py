#!/usr/bin/env python3
"""Ufone portal credentials for the PK VPS bridge.

Source of truth: `ufone_account` rows from Fleet → Ufone Accounts (Add Account).
Never reads UFONE_USERNAME / UFONE_PASSWORD from .env.

Decrypt uses the same key materials as Flask (services/ufone_service):
  UFONE_CRYPTO_KEY, UFONE_BRIDGE_TOKEN, derived(SECRET_KEY), SECRET_KEY
Preferred is UFONE_BRIDGE_TOKEN when set (shared with Render).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from typing import List, Optional, Tuple

logger = logging.getLogger('ufone-bridge-creds')

AccountLogin = Tuple[int, str, str]  # account_id, username, password


def _env(name: str, default: str = '') -> str:
    return (os.environ.get(name) or default).strip()


def _int_env(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _password_materials() -> List[str]:
    mats: List[str] = []
    for name in ('UFONE_CRYPTO_KEY', 'UFONE_BRIDGE_TOKEN'):
        v = _env(name)
        if v and v not in mats:
            mats.append(v)
    secret = _env('SECRET_KEY')
    if secret:
        derived = hmac.new(
            secret.encode('utf-8'), b'ufone-bridge-v1', hashlib.sha256,
        ).hexdigest()
        if derived and derived not in mats:
            mats.append(derived)
        if secret not in mats:
            mats.append(secret)
    return mats


def decrypt_password_enc(password_enc: str) -> str:
    """Decrypt UfoneAccount.password_enc using shared key materials."""
    if not password_enc:
        return ''
    materials = _password_materials()
    if not materials:
        logger.warning(
            'No UFONE_BRIDGE_TOKEN / SECRET_KEY — cannot decrypt ufone_account'
        )
        return ''
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        raise RuntimeError(
            'cryptography package required to decrypt UI passwords '
            '(pip install cryptography)'
        ) from e
    for material in materials:
        key = base64.urlsafe_b64encode(
            hashlib.sha256(material.encode()).digest()
        )
        try:
            return Fernet(key).decrypt(password_enc.encode()).decode()
        except Exception:
            continue
    logger.warning('ufone password decrypt failed with all key materials')
    return ''


def _db_url() -> str:
    url = _env('DATABASE_URL')
    if not url:
        raise RuntimeError('DATABASE_URL required to load Ufone accounts')
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    return url


def load_accounts_from_db(
    preferred_id: int = 0,
    conn=None,
) -> List[AccountLogin]:
    """Load active UfoneAccount rows and decrypt passwords.

    preferred_id > 0 → only that id (if active).
    preferred_id == 0 → all active, lowest id first.
    """
    import psycopg2
    import psycopg2.extras

    own = conn is None
    if own:
        conn = psycopg2.connect(_db_url(), connect_timeout=20)
    out: List[AccountLogin] = []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if preferred_id > 0:
                cur.execute(
                    """
                    SELECT id, username, password_enc, label
                    FROM ufone_account
                    WHERE id = %s AND COALESCE(is_active, true) = true
                    """,
                    (preferred_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, username, password_enc, label
                    FROM ufone_account
                    WHERE COALESCE(is_active, true) = true
                    ORDER BY id ASC
                    """
                )
            rows = cur.fetchall() or []
        for row in rows:
            username = (row.get('username') or '').strip()
            password = decrypt_password_enc(row.get('password_enc') or '')
            if not username or not password:
                logger.warning(
                    'ufone_account id=%s label=%r skipped '
                    '(empty username or decrypt failed — ensure '
                    'UFONE_BRIDGE_TOKEN matches Render; passwords rewrap on deploy)',
                    row.get('id'), row.get('label'),
                )
                continue
            out.append((int(row['id']), username, password))
        return out
    finally:
        if own:
            conn.close()


def resolve_ufone_logins() -> List[AccountLogin]:
    """Active Fleet UI accounts only. No .env username/password fallback.

    Optional env:
      UFONE_ACCOUNT_ID=N  when >0 pin to that ufone_account.id; 0 = all active
    """
    materials = _password_materials()
    if not materials:
        raise RuntimeError(
            'UFONE_BRIDGE_TOKEN (or SECRET_KEY) required on VPS to decrypt '
            'Ufone Accounts passwords from the database'
        )
    preferred = _int_env('UFONE_ACCOUNT_ID', 0)
    try:
        db_logins = load_accounts_from_db(preferred_id=preferred)
    except Exception as e:
        raise RuntimeError(f'ufone_account load failed: {e}') from e

    if not db_logins:
        raise RuntimeError(
            'No active ufone_account with decryptable password. '
            'Add/activate account in Fleet → Ufone Accounts, ensure '
            'UFONE_BRIDGE_TOKEN matches Render, and wait for password rewrap '
            '(or re-save each account password once after deploy).'
        )

    for aid, user, _ in db_logins:
        logger.info(
            'Ufone login from UI (ufone_account) id=%s username=%s',
            aid, user,
        )
    return db_logins


def resolve_ufone_login() -> AccountLogin:
    """Single login (first active UI account)."""
    return resolve_ufone_logins()[0]


def resolve_ufone_login_for_account(account_id: int) -> AccountLogin:
    """Login for a specific account id (on-demand detail for that account)."""
    if not account_id or int(account_id) <= 0:
        return resolve_ufone_login()
    if not _password_materials():
        raise RuntimeError(
            'UFONE_BRIDGE_TOKEN required on VPS to decrypt Ufone Accounts'
        )
    try:
        found = load_accounts_from_db(preferred_id=int(account_id))
    except Exception as e:
        raise RuntimeError(
            f'ufone_account id={account_id} load failed: {e}'
        ) from e
    if not found:
        raise RuntimeError(
            f'No active ufone_account id={account_id} '
            '(or password decrypt failed — check UFONE_BRIDGE_TOKEN / rewrap)'
        )
    aid, user, _pw = found[0]
    logger.info(
        'Ufone login from UI id=%s username=%s (detail request)',
        aid, user,
    )
    return found[0]
