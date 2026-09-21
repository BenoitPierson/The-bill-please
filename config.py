"""Application settings, read from the environment with sane local defaults."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Everything mutable (tenant databases, uploaded originals) lives under DATA_DIR,
# so a deployment only has to persist/back up that single directory.
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data")))
TENANTS_DIR = DATA_DIR / "tenants"

# Tenant used when the request has no usable subdomain — i.e. local use on
# 127.0.0.1. In production each client reaches its own <slug>.domain.tld.
DEFAULT_TENANT = os.environ.get("DEFAULT_TENANT", "local")

# The domain the platform is served from, e.g. "factures.example.com". Set it in
# production: it is what separates a tenant subdomain (acme.factures.example.com)
# from the bare application domain, which no heuristic can tell apart on its own.
APP_DOMAIN = os.environ.get("APP_DOMAIN", "").strip().lower().lstrip(".")

# Host suffixes that never carry a tenant subdomain.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}

MAX_CONCURRENT_EXTRACTIONS = int(os.environ.get("MAX_CONCURRENT_EXTRACTIONS", "8"))

# Time one worker spends on one invoice (store, render pages, Claude call, insert).
# Measured median on the reference dataset: ~10 s, of which ~7 s is the Claude
# call. Only used for the remaining-time estimate before the first invoices of a
# batch complete; after that the estimate follows the observed throughput.
ESTIMATED_SECONDS_PER_INVOICE = float(os.environ.get("ESTIMATED_SECONDS_PER_INVOICE", "10"))

# Number of pending corrections on a supplier before its extraction rules are
# refreshed automatically (see learning.py).
AUTO_LEARN_THRESHOLD = int(os.environ.get("AUTO_LEARN_THRESHOLD", "3"))

# Storage cap applied to every client workspace that has no quota of its own
# (set per client with `manage.py set-quota`). 0 means unlimited.
DEFAULT_STORAGE_QUOTA_MB = int(os.environ.get("DEFAULT_STORAGE_QUOTA_MB", "0"))

# Largest single upload accepted, in MB. The request is read into memory before
# it is expanded, so this is also the cap on what one user can make the server
# hold at once. 0 disables the check.
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "500"))

SESSION_COOKIE = "invoice_session"
SESSION_MAX_AGE = 60 * 60 * 12  # 12 hours

# Session cookies must be HTTPS-only in production. Defaults to on as soon as
# APP_DOMAIN is set (i.e. not a local run); SESSION_HTTPS_ONLY overrides it.
_https_only = os.environ.get("SESSION_HTTPS_ONLY")
SESSION_HTTPS_ONLY = bool(APP_DOMAIN) if _https_only is None else _https_only.lower() in ("1", "true", "yes")


def session_secret() -> str:
    """Key used to sign session cookies.

    Set SESSION_SECRET in production (rotating it logs everyone out). Locally a
    random key is generated once and kept in DATA_DIR so restarts don't drop
    the current session.
    """
    from_env = os.environ.get("SESSION_SECRET")
    if from_env:
        return from_env

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key_file = DATA_DIR / "session_secret.txt"
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    return key_file.read_text(encoding="utf-8").strip()
