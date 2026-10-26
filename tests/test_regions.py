from __future__ import annotations

import json

import db
from extraction import INVOICE_SCHEMA, clean_regions


def test_regions_keep_only_uncertain_fields():
    raw = [{"field": "invoice_number", "page": 1, "x": .1, "y": .2, "width": .3, "height": .05},
           {"field": "supplier_name", "page": 1, "x": .1, "y": .1, "width": .2, "height": .05}]
    assert [r["field"] for r in clean_regions(raw, ["invoice_number"], 1)] == ["invoice_number"]


def test_regions_drop_pages_out_of_range_and_empty_boxes():
    raw = [{"field": "invoice_date", "page": 3, "x": .1, "y": .1, "width": .1, "height": .1},
           {"field": "invoice_date", "page": 1, "x": .1, "y": .1, "width": 0, "height": .1}]
    assert clean_regions(raw, ["invoice_date"], 2) == []


def test_regions_are_clamped_to_the_page():
    raw = [{"field": "total_amount", "page": 1, "x": -.2, "y": .9, "width": .5, "height": .4}]
    (box,) = clean_regions(raw, ["total_amount"], 1)
    assert box["x"] == 0.0 and box["y"] == 0.9
    assert box["width"] == 0.5 and box["height"] == 0.1


def test_regions_ignore_garbage():
    assert clean_regions("nope", ["total_amount"], 1) == []
    assert clean_regions([{"field": "total_amount", "page": "a"}], ["total_amount"], 1) == []


def test_schema_requires_regions():
    assert "uncertain_regions" in INVOICE_SCHEMA["required"]


def test_insert_invoice_stores_regions(tenant):
    box = {"field": "total_amount", "page": 1, "x": .1, "y": .1, "width": .2, "height": .05}
    invoice_id = db.insert_invoice(tenant, {"filename": "f.pdf", "uncertain_regions": [box]})
    assert json.loads(db.get_invoice(tenant, invoice_id)["uncertain_regions"]) == [box]
