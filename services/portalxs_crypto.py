# -*- coding: utf-8 -*-
"""
PortalXS Local Encryption (CRACKED)
====================================
Algorithm: Triple DES (DES-EDE2)
Mode:      ECB
Key:       MD5(SERVER_KEY) = MD5("TWSouth")  -> 16 bytes
Padding:   PKCS7
Output:    Base64

Yeh server ki Server_EncryptMessage/DecryptMessage ke barabar hai.
Ab humein bar bar server ko encryption ke liye call nahi karni.
"""
import hashlib
import base64
from Crypto.Cipher import DES3
from Crypto.Util.Padding import pad, unpad

SERVER_KEY = "TWSouth"


def _key():
    """3DES key = MD5(serverKey) -> 16 bytes (DES-EDE2)."""
    return hashlib.md5(SERVER_KEY.encode()).digest()  # 16 bytes


def encrypt(plaintext: str) -> str:
    """Encrypt string -> Base64 (same as server Server_EncryptMessage)."""
    key = _key()
    data = plaintext.encode("utf-8")
    padded = pad(data, 8)
    cipher = DES3.new(key, DES3.MODE_ECB)
    enc = cipher.encrypt(padded)
    return base64.b64encode(enc).decode()


def decrypt(b64_ciphertext: str) -> str:
    """Decrypt Base64 -> string (same as server Server_DecryptMessage)."""
    key = _key()
    data = base64.b64decode(b64_ciphertext)
    cipher = DES3.new(key, DES3.MODE_ECB)
    dec = cipher.decrypt(data)
    return unpad(dec, 8).decode("utf-8")


if __name__ == "__main__":
    # Self-test against known server values
    print("=== Self-test against server-encrypted values ===")
    cases = [
        ("hello", "R9edAvNeUGw="),
        ("1", "2Sl3Z1hUAMQ="),
        ("hello world", "7SnpIfuZvBv7Y8qDTh4X+w=="),
    ]
    all_pass = True
    for plain, expected in cases:
        got = encrypt(plain)
        ok = got == expected
        if not ok: all_pass = False
        print(f"  encrypt({plain!r:15s}) = {got:30s} expected {expected:30s} {'PASS' if ok else 'FAIL'}")

        # round-trip decrypt
        back = decrypt(expected)
        ok2 = back == plain
        print(f"  decrypt({expected:30s}) = {back!r:15s} {'PASS' if ok2 else 'FAIL'}")

    print()
    print("ALL TESTS PASSED" if all_pass else "SOME TESTS FAILED")
