"""Shared fixtures: every test gets its own throwaway tenant directory."""
from __future__ import annotations

import pytest

import db
import tenants


@pytest.fixture
def tenant(tmp_path, monkeypatch):
    monkeypatch.setattr(tenants, "TENANTS_DIR", tmp_path / "tenants")
    db._initialised.clear()
    tenants.create("test")
    return "test"
