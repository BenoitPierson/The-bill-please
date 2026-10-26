from __future__ import annotations

import fitz
import pytest
from PIL import Image
from starlette.testclient import TestClient

import app as app_module
import auth
import db
import documents
import tenants


@pytest.fixture
def client(tenant, monkeypatch):
    monkeypatch.setattr(app_module, "DEFAULT_TENANT", tenant)
    monkeypatch.setattr(tenants, "DEFAULT_TENANT", tenant)
    db.create_user(tenant, "a@b.fr", auth.hash_password("motdepasse1"))
    test_client = TestClient(app_module.app)
    test_client.post("/login", data={"email": "a@b.fr", "password": "motdepasse1"})
    return test_client


@pytest.fixture
def pdf_invoice(tenant):
    invoice_id = "pdfinvoice0001"
    doc = fitz.open()
    for n in range(2):
        doc.new_page().insert_text((72, 72), "Page {}".format(n + 1))
    path = tenants.files_dir(tenant) / "{}.pdf".format(invoice_id)
    doc.save(str(path))
    doc.close()
    db.insert_invoice(tenant, {"id": invoice_id, "filename": "x.pdf", "stored_name": path.name})
    return invoice_id


def test_pdf_page_is_rendered_as_png(client, pdf_invoice):
    response = client.get(f"/invoices/{pdf_invoice}/pages/2.png")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert "no-store" in response.headers["cache-control"]


def test_page_out_of_range_is_404(client, pdf_invoice):
    assert client.get(f"/invoices/{pdf_invoice}/pages/3.png").status_code == 404
    assert client.get(f"/invoices/{pdf_invoice}/pages/0.png").status_code == 404


def test_missing_file_on_disk_is_404(client, tenant, pdf_invoice):
    (tenants.files_dir(tenant) / db.get_invoice(tenant, pdf_invoice)["stored_name"]).unlink()
    assert client.get(f"/invoices/{pdf_invoice}/pages/1.png").status_code == 404


def test_api_detail_reports_pages_and_regions(client, pdf_invoice):
    data = client.get(f"/api/invoices/{pdf_invoice}").json()
    assert data["page_count"] == 2 and data["document_kind"] == "pdf" and data["uncertain_regions"] == []


def test_documents_page_count_of_an_image(tmp_path):
    path = tmp_path / "x.png"
    Image.new("RGB", (10, 10)).save(path)
    assert documents.page_count(path) == 1
