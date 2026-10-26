from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

import app as app_module
import auth
import db
import learning
import tenants


def add(slug, **fields):
    record = {"filename": "f.pdf"}
    record.update(fields)
    return db.insert_invoice(slug, record)


@pytest.fixture
def client(tenant, monkeypatch):
    monkeypatch.setattr(app_module, "DEFAULT_TENANT", tenant)
    monkeypatch.setattr(tenants, "DEFAULT_TENANT", tenant)
    db.create_user(tenant, "a@b.fr", auth.hash_password("motdepasse1"))
    test_client = TestClient(app_module.app)
    test_client.post("/login", data={"email": "a@b.fr", "password": "motdepasse1"})
    return test_client


def test_confirm_removes_doubt_and_region_and_records_confirmation(client, tenant):
    box = {"field": "invoice_number", "page": 1, "x": .1, "y": .1, "width": .2, "height": .05}
    iid = add(tenant, invoice_number="A1", uncertain_fields=["invoice_number"], uncertain_regions=[box])
    body = client.post(f"/api/invoices/{iid}/confirm", json={"field": "invoice_number"}).json()
    assert body["uncertain_fields"] == [] and body["uncertain_regions"] == []
    (c,) = db.pending_corrections(tenant)
    assert c["kind"] == "confirmation" and c["old_value"] == c["new_value"] == "A1"
    assert "invoice_number" not in json.loads(db.get_invoice(tenant, iid)["edited_fields"])


def test_confirm_rejects_a_field_that_is_not_doubtful(client, tenant):
    iid = add(tenant, invoice_number="A1")
    assert client.post(f"/api/invoices/{iid}/confirm", json={"field": "invoice_number"}).status_code == 400
    assert client.post(f"/api/invoices/{iid}/confirm", json={"field": "filename"}).status_code == 400


def test_validate_confirms_every_doubtful_field(client, tenant):
    iid = add(tenant, uncertain_fields=["invoice_number", "invoice_date"])
    assert client.post(f"/api/invoices/{iid}/validate").json()["uncertain_fields"] == []
    assert len(db.pending_corrections(tenant)) == 2


def test_validate_refuses_an_invoice_in_error(client, tenant):
    iid = add(tenant, error="Erreur API : x", uncertain_fields=["invoice_number"])
    assert client.post(f"/api/invoices/{iid}/validate").status_code == 400


def test_confirmations_reach_the_learning_threshold(client, tenant, monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "get_client", lambda: None)
    monkeypatch.setattr(learning, "refresh_rules",
                        lambda c, s: calls.append(s) or {"corrections": 3, "rules_updated": 1})
    iid = add(tenant, uncertain_fields=["invoice_number", "invoice_date", "currency"])
    client.post(f"/api/invoices/{iid}/validate")
    assert calls == [tenant]


def test_confirmed_then_corrected_field_is_marked_edited(client, tenant):
    iid = add(tenant, invoice_number="A1", uncertain_fields=["invoice_number"])
    client.post(f"/api/invoices/{iid}/confirm", json={"field": "invoice_number"})
    client.patch(f"/api/invoices/{iid}", json={"field": "invoice_number", "value": "A2"})
    assert json.loads(db.get_invoice(tenant, iid)["edited_fields"]) == ["invoice_number"]
    assert [c["kind"] for c in db.pending_corrections(tenant)] == ["confirmation", "correction"]


def test_correcting_a_field_removes_its_region(client, tenant):
    box = {"field": "invoice_date", "page": 1, "x": .1, "y": .1, "width": .2, "height": .05}
    iid = add(tenant, invoice_date="2026-01-02", uncertain_fields=["invoice_date"], uncertain_regions=[box])
    client.patch(f"/api/invoices/{iid}", json={"field": "invoice_date", "value": "2026-02-01"})
    assert json.loads(db.get_invoice(tenant, iid)["uncertain_regions"]) == []


def _learning_runs_off_the_event_loop(monkeypatch):
    """The rule distillation is a multi-second Claude call: run on the event
    loop it would freeze every tenant's requests, import polling included."""
    import asyncio

    seen = []

    def refresh(client, slug):
        try:
            asyncio.get_running_loop()
            seen.append("event loop")
        except RuntimeError:
            seen.append("worker thread")
        return {"corrections": 3, "rules_updated": 0}

    monkeypatch.setattr(app_module, "AUTO_LEARN_THRESHOLD", 1)
    monkeypatch.setattr(app_module, "get_client", lambda: None)
    monkeypatch.setattr(learning, "refresh_rules", refresh)
    return seen


def test_confirm_learns_off_the_event_loop(client, tenant, monkeypatch):
    seen = _learning_runs_off_the_event_loop(monkeypatch)
    iid = add(tenant, invoice_number="A1", uncertain_fields=["invoice_number"])
    client.post(f"/api/invoices/{iid}/confirm", json={"field": "invoice_number"})
    assert seen == ["worker thread"]


def test_correction_learns_off_the_event_loop(client, tenant, monkeypatch):
    seen = _learning_runs_off_the_event_loop(monkeypatch)
    iid = add(tenant, invoice_number="A1")
    client.patch(f"/api/invoices/{iid}", json={"field": "invoice_number", "value": "B2"})
    assert seen == ["worker thread"]
