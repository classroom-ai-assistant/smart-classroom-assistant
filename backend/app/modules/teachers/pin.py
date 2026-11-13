"""Hashing for the kids-mode PIN (AUTH-09).

Uses scrypt from the standard library, so no extra dependency. A 4–6 digit
PIN has few possible values, so the hash only protects it if the database
leaks; the real protection against guessing is rate-limiting the verify
endpoint, which comes with the session slice.
"""

import base64
import hashlib
import hmac
import secrets

_N, _R, _P = 2**14, 8, 1
_PREFIX = "scrypt"


def hash_pin(pin: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(pin.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "$".join(
        [_PREFIX, str(_N), str(_R), str(_P), base64.b64encode(salt).decode(), base64.b64encode(digest).decode()]
    )


def verify_pin(pin: str, stored: str) -> bool:
    try:
        prefix, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if prefix != _PREFIX:
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            pin.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r), p=int(p), dklen=len(expected)
        )
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)
