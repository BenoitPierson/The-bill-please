"""Tenant registry.

Each client company is a directory under DATA_DIR/tenants/<slug>/ holding its
own SQLite database and its own uploaded originals. The filesystem *is* the
registry — there is no shared table listing tenants, and no shared table
holding their data, so one client's rows can never be returned to another.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import APP_DOMAIN, DEFAULT_STORAGE_QUOTA_MB, DEFAULT_TENANT, LOCAL_HOSTS, TENANTS_DIR

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")


def is_valid_slug(slug: str) -> bool:
    return bool(SLUG_PATTERN.match(slug or ""))


def tenant_dir(slug: str) -> Path:
    if not is_valid_slug(slug):
        raise ValueError("Identifiant de client invalide : {!r}".format(slug))
    return TENANTS_DIR / slug


def database_path(slug: str) -> Path:
    return tenant_dir(slug) / "data.db"


def files_dir(slug: str) -> Path:
    return tenant_dir(slug) / "files"


def exists(slug: str) -> bool:
    return is_valid_slug(slug) and tenant_dir(slug).is_dir()


def _read_meta(slug: str) -> Dict[str, Any]:
    meta = tenant_dir(slug) / "tenant.json"
    if meta.exists():
        try:
            return json.loads(meta.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    return {}


def _write_meta(slug: str, values: Dict[str, Any]) -> None:
    meta = _read_meta(slug)
    meta.update(values)
    (tenant_dir(slug) / "tenant.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def display_name(slug: str) -> str:
    return _read_meta(slug).get("display_name", slug)


def storage_usage(slug: str) -> Dict[str, int]:
    """Bytes actually on disk for a client: stored originals plus its database.

    Measured on disk rather than summed from the database, so files left behind
    by an interrupted import are counted too.
    """
    files_bytes = file_count = 0
    directory = files_dir(slug)
    if directory.is_dir():
        with os.scandir(str(directory)) as entries:
            for entry in entries:
                if entry.is_file():
                    files_bytes += entry.stat().st_size
                    file_count += 1

    db_bytes = 0
    database = database_path(slug)
    # WAL mode keeps recent writes in side files until checkpoint.
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(database) + suffix)
        if path.is_file():
            db_bytes += path.stat().st_size

    return {
        "files_bytes": files_bytes,
        "file_count": file_count,
        "db_bytes": db_bytes,
        "total_bytes": files_bytes + db_bytes,
    }


def storage_quota_bytes(slug: str) -> int:
    """The client's storage cap in bytes; 0 means unlimited."""
    quota_mb = _read_meta(slug).get("storage_quota_mb")
    if quota_mb is None:
        quota_mb = DEFAULT_STORAGE_QUOTA_MB
    return max(0, int(quota_mb)) * 1024 * 1024


def set_storage_quota(slug: str, quota_mb: int) -> None:
    _write_meta(slug, {"storage_quota_mb": max(0, int(quota_mb))})


def create(slug: str, name: Optional[str] = None) -> Path:
    """Create the directory layout for a new client. Idempotent."""
    directory = tenant_dir(slug)
    files_dir(slug).mkdir(parents=True, exist_ok=True)
    meta = directory / "tenant.json"
    if not meta.exists():
        meta.write_text(
            json.dumps({"slug": slug, "display_name": name or slug}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return directory


def list_slugs() -> List[str]:
    if not TENANTS_DIR.is_dir():
        return []
    return sorted(p.name for p in TENANTS_DIR.iterdir() if p.is_dir() and is_valid_slug(p.name))


def resolve_from_host(host: str) -> str:
    """Pick the tenant a request belongs to, from the Host header.

    With APP_DOMAIN set (production), a tenant is exactly one label in front of
    it: `acme.factures.example.com` -> "acme", while the bare `factures.example.com`
    is the application domain and falls back to DEFAULT_TENANT. Without it
    (local use), any host that is not localhost is read as `<slug>.domain.tld`.
    """
    hostname = (host or "").split(":")[0].strip().lower().rstrip(".")
    if not hostname or hostname in LOCAL_HOSTS:
        return DEFAULT_TENANT

    if APP_DOMAIN:
        if hostname == APP_DOMAIN or not hostname.endswith("." + APP_DOMAIN):
            return DEFAULT_TENANT
        prefix = hostname[: -(len(APP_DOMAIN) + 1)]
        # Exactly one label in front of the app domain, and a valid slug.
        if "." in prefix or prefix == "www" or not is_valid_slug(prefix):
            return DEFAULT_TENANT
        return prefix

    labels = hostname.split(".")
    # Needs at least sub.domain.tld for the first label to be a tenant slug.
    if len(labels) >= 3 and is_valid_slug(labels[0]) and labels[0] != "www":
        return labels[0]
    return DEFAULT_TENANT
