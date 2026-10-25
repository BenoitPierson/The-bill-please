from __future__ import annotations

from datetime import date

from dashboard import last_complete_month, main_currency, month_name, month_window, top_price_alerts


def test_last_complete_month_regular():
    assert last_complete_month(date(2026, 10, 25)) == (2026, 9)


def test_last_complete_month_january():
    assert last_complete_month(date(2027, 1, 1)) == (2026, 12)


def test_month_window_includes_current_month_and_crosses_year():
    window = month_window(date(2026, 3, 4))
    assert len(window) == 12
    assert window[0] == "2025-04" and window[-1] == "2026-03"


def test_month_name():
    assert month_name(2026, 9) == "septembre 2026"


def test_main_currency_by_count():
    rows = [{"currency": "KES", "amount": 10.0, "invoice_count": 5},
            {"currency": "USD", "amount": 900.0, "invoice_count": 2}]
    assert main_currency(rows) == "KES"


def test_main_currency_tie_broken_by_amount_then_name():
    rows = [{"currency": "USD", "amount": 50.0, "invoice_count": 3},
            {"currency": "EUR", "amount": 80.0, "invoice_count": 3}]
    assert main_currency(rows) == "EUR"
    same = [{"currency": "USD", "amount": 50.0, "invoice_count": 3},
            {"currency": "EUR", "amount": 50.0, "invoice_count": 3}]
    assert main_currency(same) == "EUR"


def test_main_currency_ignores_blank_unless_alone():
    rows = [{"currency": "", "amount": 10.0, "invoice_count": 9},
            {"currency": "KES", "amount": 5.0, "invoice_count": 1}]
    assert main_currency(rows) == "KES"
    assert main_currency([{"currency": "", "amount": 1.0, "invoice_count": 1}]) == ""


def test_main_currency_empty():
    assert main_currency([]) is None


def test_top_price_alerts_keeps_three_highest_drifts():
    summary = [{"alert": True, "drift": 26.0}, {"alert": False, "drift": 90.0},
               {"alert": True, "drift": 31.0}, {"alert": True, "drift": 27.0},
               {"alert": True, "drift": 40.0}]
    assert [a["drift"] for a in top_price_alerts(summary)] == [40.0, 31.0, 27.0]
