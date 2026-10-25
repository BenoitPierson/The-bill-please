from __future__ import annotations

import db


def add(slug, **fields):
    record = {"filename": "f.pdf"}
    record.update(fields)
    return db.insert_invoice(slug, record)


def test_totals_by_currency_excludes_errors_and_bad_dates(tenant):
    add(tenant, invoice_date="2026-09-03", total_amount=100.0, currency="KES")
    add(tenant, invoice_date="2026-09-20", total_amount=50.0, currency="USD")
    add(tenant, invoice_date="2026-09-21", total_amount=999.0, currency="KES", error="Erreur API : x")
    add(tenant, invoice_date="sept 2026", total_amount=999.0, currency="KES")
    rows = {r["currency"]: r for r in db.totals_by_currency(tenant, "2026-09", "2026-09")}
    assert rows["KES"]["amount"] == 100.0 and rows["KES"]["invoice_count"] == 1
    assert rows["USD"]["amount"] == 50.0


def test_totals_by_currency_blank_currency(tenant):
    add(tenant, invoice_date="2026-09-03", total_amount=7.0)
    (row,) = db.totals_by_currency(tenant, "2026-01", "2026-12")
    assert row["currency"] == "" and row["amount"] == 7.0


def test_monthly_series_fills_missing_months(tenant):
    add(tenant, invoice_date="2026-08-10", total_amount=10.0, currency="KES")
    add(tenant, invoice_date="2026-08-11", total_amount=99.0, currency="USD")
    series = db.monthly_series(tenant, ["2026-08", "2026-09", "2026-10"], "KES")
    assert [(r["period"], r["amount"]) for r in series] == [
        ("2026-08", 10.0), ("2026-09", 0.0), ("2026-10", 0.0)]


def test_latest_invoices_by_import_order(tenant):
    for n in range(4):
        add(tenant, invoice_number="N{}".format(n), invoice_date="2026-01-0{}".format(n + 1))
    latest = db.latest_invoices(tenant)
    assert [r["invoice_number"] for r in latest] == ["N3", "N2", "N1"]
    assert latest[0]["uncertain_fields"] == []


def test_count_uncertain_ignores_errors(tenant):
    add(tenant, uncertain_fields=["invoice_number"])
    add(tenant, uncertain_fields=["invoice_date"], error="Erreur API : x")
    add(tenant)
    assert db.count_uncertain(tenant) == 1


def test_heatmap_rows_collects_numbers(tenant):
    add(tenant, supplier_name="Bidco", invoice_date="2026-09-03", total_amount=5.0, invoice_number="A1")
    add(tenant, supplier_name="Bidco", invoice_date="2026-09-03", total_amount=7.0, invoice_number="A2")
    add(tenant, supplier_name="Bidco", invoice_date="2026-09-03", total_amount=70.0, error="Erreur API : x")
    (row,) = db.heatmap_rows(tenant)
    assert row["amount"] == 12.0 and row["invoice_count"] == 2
    assert sorted(row["invoice_numbers"]) == ["A1", "A2"]


def test_latest_batch_none_then_most_recent(tenant):
    assert db.latest_batch(tenant) is None
    db.create_batch(tenant, "a.zip", 1)
    second = db.create_batch(tenant, "b.zip", 1)
    assert db.latest_batch(tenant)["id"] == second


def test_heatmap_rows_can_be_restricted_to_one_currency(tenant):
    add(tenant, supplier_name="Bidco", invoice_date="2026-09-03", total_amount=5.0, currency="KES")
    add(tenant, supplier_name="Bidco", invoice_date="2026-09-03", total_amount=900.0, currency="USD")
    (row,) = db.heatmap_rows(tenant, "KES")
    assert row["amount"] == 5.0
