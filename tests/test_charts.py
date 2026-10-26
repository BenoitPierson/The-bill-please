from __future__ import annotations

import charts


def _lightness(rgb):
    r, g, b = (c / 255 for c in rgb)
    return (max(r, g, b) + min(r, g, b)) / 2


def test_heat_stops_lightness_strictly_decreases():
    values = [_lightness(rgb) for _, rgb in charts.HEAT_STOPS]
    assert all(a > b for a, b in zip(values, values[1:]))


def test_heat_stops_go_from_green_to_red():
    first, last = charts.HEAT_STOPS[0][1], charts.HEAT_STOPS[-1][1]
    assert first[1] > first[0] and last[0] > last[1]


def test_heat_stops_are_desaturated():
    for _, (r, g, b) in charts.HEAT_STOPS:
        assert max(r, g, b) - min(r, g, b) <= 110


def test_monthly_columns_marks_current_month():
    rows = [{"period": "2026-09", "amount": 100.0, "invoice_count": 3},
            {"period": "2026-10", "amount": 20.0, "invoice_count": 1}]
    bars = charts.monthly_columns(rows, current_period="2026-10")["bars"]
    assert [b["is_current"] for b in bars] == [False, True]


def test_monthly_columns_peak_ignores_current_month():
    rows = [{"period": "2026-09", "amount": 100.0, "invoice_count": 3},
            {"period": "2026-10", "amount": 300.0, "invoice_count": 9}]
    bars = charts.monthly_columns(rows, current_period="2026-10")["bars"]
    assert [b["show_value"] for b in bars] == [True, False]


def test_heatmap_tooltip_data():
    rows = [{"day": "2026-09-03", "supplier": "Bidco", "amount": 30.0, "invoice_count": 2, "invoice_numbers": ["A1", "A2"]},
            {"day": "2026-09-10", "supplier": "Bidco", "amount": 70.0, "invoice_count": 1, "invoice_numbers": ["A3"]},
            {"day": "2026-09-03", "supplier": "Freshchips", "amount": 20.0, "invoice_count": 1, "invoice_numbers": []}]
    cell = next(c for c in charts.daily_heatmap(rows)["cells"]
                if c["supplier"] == "Bidco" and c["date_text"].startswith("3 "))
    assert cell["numbers"] == ["A1", "A2"]
    assert cell["day_total_text"] == charts.format_amount(50.0)
    assert cell["month_share_text"] == charts.format_percent(30.0)
    assert "fill_rel" not in cell


def test_heatmap_hides_numbers_beyond_three():
    rows = [{"day": "2026-09-03", "supplier": "X", "amount": 1.0, "invoice_count": 4,
             "invoice_numbers": ["1", "2", "3", "4"]}]
    assert charts.daily_heatmap(rows)["cells"][0]["numbers"] == []
