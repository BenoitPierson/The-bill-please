"""Per-product cost statistics.

The Products tab answers two questions: is a unit price drifting, and is a
product being ordered more often. Both are computed here from the raw invoice
lines, so the aggregation is testable without a database and the SQL stays a
plain SELECT.

Grouping key: product + supplier + unit + currency. The unit belongs in the key
because 2 EUR per kg and 2 EUR per carton are not the same price, and comparing
them would raise alerts that mean nothing.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Sequence

from extraction import PRODUCT_CATEGORIES

DEFAULT_ALERT_THRESHOLD = 25  # percent above the average before a price is flagged

_CATEGORY_RANK = {name: index for index, name in enumerate(PRODUCT_CATEGORIES)}

UNIT_LABELS = {
    "kg": "kg", "g": "g", "l": "L", "cl": "cl", "piece": "piece", "lot": "lot",
    "carton": "carton", "palette": "palette", "m": "m", "m2": "m²",
    "heure": "heure", "jour": "jour",
}


def unit_label(unit: Optional[str]) -> str:
    return UNIT_LABELS.get(unit or "", unit or "—")


_PUNCTUATION = re.compile(r"[^a-z0-9]+")


def canonical(text: Optional[str]) -> str:
    """Fold a wording down to what it has in common with its variants.

    The model is asked for a generic singular key, but it does not hold that
    line perfectly: the same invoice wording came back as both "frite" and
    "frites", which split one product into two rows. Accents, case, spacing and
    a trailing plural are removed here so the key only has to be *consistent*,
    not linguistically right — "frites" and "frite" both fold to "frite".
    Words shorter than four letters keep their final s ("jus", "riz").
    """
    stripped = unicodedata.normalize("NFKD", (text or "").strip().lower())
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    # One-letter words are elided articles ("jus d'orange" / "jus orange"):
    # they vary with the wording and carry nothing.
    words = [w for w in _PUNCTUATION.split(stripped) if len(w) > 1]
    folded = [w[:-1] if len(w) >= 4 and w[-1] in ("s", "x") else w for w in words]
    return " ".join(folded)


# Words that say nothing about *which* company this is. Dropped before two
# supplier names are compared, so "FRESHCHIPS LIMITED" and "FRESHCHIPS
# PROCESSORS LIMITED" can be recognised as one.
LEGAL_FORMS = {
    "limited", "ltd", "llc", "plc", "inc", "incorporated", "corp", "corporation",
    "company", "co", "sarl", "sas", "sasu", "sa", "eurl", "snc", "scop", "gmbh",
    "bv", "nv", "spa", "srl", "ag", "pty", "kenya", "ke", "eu", "the", "et", "and",
}


def _supplier_words(name: str) -> List[str]:
    """Distinctive words of a company name.

    Not `canonical()`: that one drops one-letter words, which is right for
    products ("jus d'orange") and wrong here — "Fournisseur A" and
    "Fournisseur B" are two companies, and dropping the letter would merge
    them. Single characters are kept; only legal forms are removed.
    """
    stripped = unicodedata.normalize("NFKD", (name or "").strip().lower())
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    words = [w for w in _PUNCTUATION.split(stripped) if w]
    folded = [w[:-1] if len(w) >= 4 and w[-1] in ("s", "x") else w for w in words]
    return [w for w in folded if w not in LEGAL_FORMS]


def resolve_suppliers(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Map every spelling of a supplier onto one name.

    Deliberately conservative: two names are merged only when, once the legal
    form is dropped, one is the other **plus** extra words — "Freshchips" and
    "Freshchips Processors" are the same company, while "Bidco Foods" and
    "Bidco Oil" are not (neither contains the other) and stay apart. Comparing
    suppliers is the point of this tab; merging two real companies would be a
    worse error than leaving two spellings side by side.
    """
    counts: Dict[str, int] = {}
    for row in rows:
        name = (row.get("supplier") or "").strip()
        if name:
            counts[name] = counts.get(name, 0) + 1

    # The most-invoiced spelling wins, and the longest breaks a tie: between
    # equals, the fuller name tells the user more.
    names = sorted(counts, key=lambda n: (-counts[n], -len(n), n))
    words = {name: set(_supplier_words(name)) for name in names}

    canonical_of: Dict[str, str] = {}
    variants: Dict[str, List[str]] = {}
    for name in names:
        if not words[name]:
            canonical_of[name] = name
            variants.setdefault(name, []).append(name)
            continue
        for chosen in variants:
            if words[name] <= words[chosen] or words[chosen] <= words[name]:
                canonical_of[name] = chosen
                variants[chosen].append(name)
                break
        else:
            canonical_of[name] = name
            variants[name] = [name]

    return {
        name: {
            "name": canonical_of[name],
            "variants": sorted(set(variants[canonical_of[name]])),
        }
        for name in names
    }


def _supplier_of(row: Dict[str, Any], suppliers: Dict[str, Dict[str, Any]]) -> str:
    raw = (row.get("supplier") or "").strip()
    return suppliers.get(raw, {}).get("name", raw)


def _resolve_variants(
    rows: Sequence[Dict[str, Any]], suppliers: Dict[str, Dict[str, Any]]
) -> Dict[tuple, Dict[str, Any]]:
    """Agree on one product key and one unit per printed wording.

    Two lines of the same supplier carrying the *same printed label* are the
    same article, whatever the model called it that day: the wording is on the
    document, the key and the unit are its reading of it. So each
    (supplier, label) group votes, and the majority wins — which is what stops
    one product from appearing twice, once per unit.
    """
    votes: Dict[tuple, Dict[str, Dict[str, int]]] = {}
    for row in rows:
        group = (_supplier_of(row, suppliers), canonical(row.get("label")))
        tally = votes.setdefault(group, {"key": {}, "unit": {}})
        key = canonical(row.get("product_key")) or group[1]
        tally["key"][key] = tally["key"].get(key, 0) + 1
        unit = row.get("unit") or ""
        tally["unit"][unit] = tally["unit"].get(unit, 0) + 1

    resolved = {}
    for group, tally in votes.items():
        unit = max(tally["unit"], key=lambda value: (tally["unit"][value], value))
        resolved[group] = {
            "key": max(tally["key"], key=lambda value: (tally["key"][value], value)),
            "unit": unit or None,
            # Kept so the table can say the unit was not read the same way
            # everywhere, instead of silently picking one.
            "unit_conflict": len([u for u in tally["unit"] if u]) > 1,
        }
    return resolved


def _most_common(values: Sequence[str]) -> str:
    counts: Dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    # Ties go to the wording seen first, so the table does not reshuffle itself.
    return max(counts, key=lambda value: (counts[value], -values.index(value)))


def _observation_at(observations: Sequence[Dict[str, Any]], price: float) -> Dict[str, Any]:
    """The invoice behind a given price — the most recent one when several match.

    A price seen twice is usually the same tariff billed again; the latest
    occurrence is the one worth opening.
    """
    matching = [o for o in observations if o["price"] == price]
    return max(matching, key=lambda o: o["date"]) if matching else {}


def summarise(rows: Sequence[Dict[str, Any]], threshold: float = DEFAULT_ALERT_THRESHOLD) -> List[Dict[str, Any]]:
    """One entry per (product, supplier, unit, currency), price drift included.

    Rows are ordered by category then by `product_key` — the generic name the
    extraction normalises every wording to. That is what puts supplier A's
    "Red tomatoes" next to supplier B's "Tomatoes" instead of leaving them
    apart in an alphabetical listing of the printed labels.
    """
    suppliers = resolve_suppliers(rows)
    resolved = _resolve_variants(rows, suppliers)
    groups: Dict[tuple, Dict[str, Any]] = {}
    for row in rows:
        price = row.get("unit_price")
        if price is None or price <= 0:
            continue
        supplier = _supplier_of(row, suppliers)
        variant = resolved[(supplier, canonical(row.get("label")))]
        key = (variant["key"], supplier, variant["unit"] or "", row.get("currency") or "")
        group = groups.setdefault(key, {
            "product_key": key[0], "supplier": key[1], "unit": variant["unit"],
            "currency": key[3], "prices": [], "observations": [], "labels": [], "names": [],
            "categories": [],
            "invoices": set(), "quantity": 0.0, "spend": 0.0, "dates": [],
            "unit_conflict": variant["unit_conflict"],
            "supplier_variants": suppliers.get((row.get("supplier") or "").strip(), {}).get("variants", []),
        })
        group["unit_conflict"] = group["unit_conflict"] or variant["unit_conflict"]
        group["prices"].append(float(price))
        # Kept so the table can say which invoice carries the lowest and the
        # highest price, and link straight to it.
        group["observations"].append({
            "price": float(price),
            "invoice_id": row.get("invoice_id"),
            "invoice_number": row.get("invoice_number"),
            "date": row.get("invoice_date") or "",
            "filename": (row.get("filename") or "").split("/")[-1],
            "has_file": bool(row.get("stored_name")),
        })
        group["labels"].append(row.get("label") or key[0])
        # The generic name as the model wrote it. `product_key` is the folded
        # form used to group ("bois" -> "boi"): a grouping token, never
        # something to show to a reader.
        group["names"].append((row.get("product_key") or key[0]).strip().lower())
        group["categories"].append(row.get("category") or "Autre")
        group["invoices"].add(row.get("invoice_id"))
        quantity = row.get("quantity")
        if quantity:
            group["quantity"] += float(quantity)
            group["spend"] += float(quantity) * float(price)
        if row.get("invoice_date"):
            group["dates"].append(row["invoice_date"])

    summary = []
    for group in groups.values():
        prices = group["prices"]
        average = sum(prices) / len(prices)
        highest = max(prices)
        lowest = min(prices)
        # How far the worst price sits above the average, in percent: the
        # number the threshold slider is compared against.
        drift = ((highest - average) / average * 100) if average else 0.0
        summary.append({
            "category": _most_common(group["categories"]),
            "product_key": group["product_key"],
            "product_name": _most_common(group["names"]),
            "label": _most_common(group["labels"]),
            "supplier": group["supplier"],
            "supplier_variants": group["supplier_variants"],
            "unit": group["unit"],
            "unit_label": unit_label(group["unit"]),
            "unit_conflict": group["unit_conflict"],
            "currency": group["currency"],
            "average": average,
            "minimum": lowest,
            "maximum": highest,
            "minimum_ref": _observation_at(group["observations"], lowest),
            "maximum_ref": _observation_at(group["observations"], highest),
            "drift": drift,
            "alert": drift > threshold,
            "invoice_count": len(group["invoices"]),
            "line_count": len(prices),
            "quantity": group["quantity"],
            "spend": group["spend"],
            "first_date": min(group["dates"]) if group["dates"] else "",
            "last_date": max(group["dates"]) if group["dates"] else "",
        })

    summary.sort(key=lambda item: (
        _CATEGORY_RANK.get(item["category"], len(_CATEGORY_RANK)),
        item["product_key"],
        item["label"],
        item["supplier"],
    ))
    return summary


def product_options(summary: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Choices for the price-history selector: a product, or a product + supplier."""
    options: List[Dict[str, Any]] = []
    seen_products = set()
    for item in summary:
        if item["product_key"] not in seen_products:
            seen_products.add(item["product_key"])
            suppliers = {r["supplier"] for r in summary if r["product_key"] == item["product_key"]}
            options.append({
                "value": item["product_key"],
                "product_key": item["product_key"],
                "supplier": "",
                "label": "{} — tous fournisseurs ({})".format(item["label"], len(suppliers)),
            })
        options.append({
            "value": "{}|{}".format(item["product_key"], item["supplier"]),
            "product_key": item["product_key"],
            "supplier": item["supplier"],
            "label": "{} — {} ({})".format(item["label"], item["supplier"], item["unit_label"]),
        })
    return options


def parse_selection(value: str) -> Dict[str, str]:
    product_key, separator, supplier = (value or "").partition("|")
    return {"product_key": product_key.strip(), "supplier": supplier.strip() if separator else ""}


def history_points(
    rows: Sequence[Dict[str, Any]], product_key: str, supplier: str = ""
) -> List[Dict[str, Any]]:
    """Every priced line of one product over time, for the scatter plot."""
    suppliers = resolve_suppliers(rows)
    resolved = _resolve_variants(rows, suppliers)
    points = []
    for row in rows:
        price = row.get("unit_price")
        if price is None or price <= 0 or not row.get("invoice_date"):
            continue
        supplier_name = _supplier_of(row, suppliers)
        variant = resolved[(supplier_name, canonical(row.get("label")))]
        # Compared on the resolved key, so the history holds every wording the
        # table merged into one row.
        if variant["key"] != product_key:
            continue
        if supplier and supplier_name != supplier:
            continue
        points.append({
            "date": row["invoice_date"],
            "price": float(price),
            "supplier": supplier_name,
            "label": row.get("label") or product_key,
            "unit": variant["unit"],
            "unit_label": unit_label(variant["unit"]),
            "currency": row.get("currency") or "",
            "invoice_id": row.get("invoice_id"),
        })
    points.sort(key=lambda point: point["date"])
    return points
