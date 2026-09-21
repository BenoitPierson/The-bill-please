"""Password hashing and session handling.

Passwords use scrypt from the standard library — memory-hard, no native
dependency to build on Windows, and good enough for a handful of accounts per
client. Sessions are signed cookies (Starlette's SessionMiddleware); no session
state is stored server-side.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from typing import Dict, Optional

import db

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_BYTES = 16


def hash_password(password: str) -> str:
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P
    )
    return "scrypt${}${}".format(salt.hex(), digest.hex())


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = (stored or "").split("$")
    except ValueError:
        return False
    if algorithm != "scrypt":
        return False

    candidate = hashlib.scrypt(
        password.encode("utf-8"),
        salt=bytes.fromhex(salt_hex),
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
    )
    return hmac.compare_digest(candidate.hex(), digest_hex)


def authenticate(slug: str, email: str, password: str) -> Optional[str]:
    """Return the user's email on success, None otherwise."""
    user = db.get_user(slug, email)
    if user is None:
        # Hash anyway so a missing account and a wrong password cost the same.
        verify_password(password, "scrypt${}${}".format("00" * SALT_BYTES, "00" * 32))
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user["email"]


# --------------------------------------------------------------- login throttling

# Password guessing is otherwise limited only by scrypt's cost. Counters live in
# the process (one server, one process): enough to make online brute force
# pointless, and it forgets everything on restart. A distributed deployment
# needs this at the reverse proxy instead.
FAILURE_WINDOW = 15 * 60
FAILURES_BEFORE_LOCK = 5
LOCK_SECONDS = 5 * 60

_failures: Dict[str, list] = {}
_failures_lock = threading.Lock()


def _prune(attempts: list, now: float) -> list:
    return [t for t in attempts if now - t < FAILURE_WINDOW]


def locked_seconds(key: str) -> int:
    """Seconds the caller must wait before another attempt is accepted."""
    now = time.time()
    with _failures_lock:
        attempts = _prune(_failures.get(key, []), now)
        _failures[key] = attempts
        if len(attempts) < FAILURES_BEFORE_LOCK:
            return 0
        return max(0, int(LOCK_SECONDS - (now - attempts[-1])))


def record_failure(key: str) -> None:
    now = time.time()
    with _failures_lock:
        _failures[key] = _prune(_failures.get(key, []), now) + [now]


def clear_failures(key: str) -> None:
    with _failures_lock:
        _failures.pop(key, None)


def password_problem(password: str) -> Optional[str]:
    if len(password or "") < 10:
        return "Le mot de passe doit contenir au moins 10 caracteres."
    return None
