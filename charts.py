"""Chart geometry for the Dashboard.

The SVG is drawn by the template, but everything numeric (scales, tick values,
bar rectangles, label positions) is computed here — Jinja is a poor place to do
arithmetic, and the geometry is the part worth keeping testable.

Mark specs follow the house data-viz rules: bars capped at 24px with a 4px
rounded data-end, a 2px surface gap between neighbours, hairline gridlines, and
labels applied selectively rather than on every mark.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

BAR_MAX_THICKNESS = 24.0
BAR_GAP = 2.0
BAR_RADIUS = 4.0

# French typography puts a narrow no-break space between thousands groups.
# Kept as an escape so it stays visible in the source.
THIN_SPACE = u"\u202f"

MONTH_NAMES = {
    "01": "janv.", "02": "fevr.", "03": "mars", "04": "avr.",
    "05": "mai", "06": "juin", "07": "juil.", "08": "aout",
    "09": "sept.", "10": "oct.", "11": "nov.", "12": "dec.",
}


def format_amount(value: Any, decimals: int = 2) -> str:
    """French-style amount: 1 234 567,89 (narrow no-break space between groups)."""
    if value is None:
        return "—"
    formatted = "{:,.{}f}".format(float(value), decimals)
    integer, _, fraction = formatted.partition(".")
    integer = integer.replace(",", THIN_SPACE)
    return "{},{}".format(integer, fraction) if fraction else integer


def format_compact(value: Any) -> str:
    """Short form for axis ticks and tips: 12,9 k / 4,2 M."""
    if value is None:
        return "—"
    number = float(value)
    for threshold, suffix in ((1e9, " Md"), (1e6, " M"), (1e3, " k")):
        if abs(number) >= threshold:
            scaled = number / threshold
            text = "{:.1f}".format(scaled).rstrip("0").rstrip(".")
            return text.replace(".", ",") + suffix
    return format_amount(number, 0)


def nice_ceiling(value: float) -> float:
    """Round a maximum up to a readable axis bound (1 / 2 / 2.5 / 5 x 10^n)."""
    if value <= 0:
        return 1.0
    magnitude = 10 ** (len(str(int(value))) - 1)
    for step in (1, 2, 2.5, 5, 10):
        candidate = step * magnitude
        if value <= candidate:
            return float(candidate)
    return float(10 * magnitude)


def _ticks(maximum: float, count: int = 4) -> List[float]:
    return [maximum * i / count for i in range(count + 1)]


def month_label(period: str) -> str:
    """'2026-02' -> 'fevr. 26'."""
    if not period or len(period) < 7:
        return period or ""
    year, month = period[:4], period[5:7]
    return "{} {}".format(MONTH_NAMES.get(month, month), year[2:])


def monthly_columns(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Column chart: invoiced amount per month."""
    width, height = 720.0, 260.0
    left, right, top, bottom = 64.0, 12.0, 18.0, 30.0
    plot_width = width - left - right
    plot_height = height - top - bottom
    baseline = top + plot_height

    if not rows:
        return {"empty": True, "width": width, "height": height}

    maximum = nice_ceiling(max(float(r["amount"]) for r in rows) or 1.0)
    band = plot_width / len(rows)
    thickness = min(BAR_MAX_THICKNESS, max(4.0, band - BAR_GAP))
    peak = max(rows, key=lambda r: float(r["amount"]))

    bars = []
    for index, row in enumerate(rows):
        amount = float(row["amount"])
        bar_height = (amount / maximum) * plot_height if maximum else 0.0
        bars.append(
            {
                "x": left + band * index + (band - thickness) / 2,
                "y": baseline - bar_height,
                "width": thickness,
                "height": max(bar_height, 1.0),
                "radius": min(BAR_RADIUS, thickness / 2),
                "center": left + band * index + band / 2,
                "label": month_label(row["period"]),
                "amount": amount,
                "amount_text": format_amount(amount),
                "count": row["invoice_count"],
                # Only the peak is labelled directly; the axis carries the rest.
                "show_value": row["period"] == peak["period"],
                "value_text": format_compact(amount),
                # Every third label when months get crowded, to avoid collisions.
                "show_label": len(rows) <= 14 or index % 2 == 0,
            }
        )

    gridlines = [
        {"y": baseline - (value / maximum) * plot_height, "label": format_compact(value)}
        for value in _ticks(maximum)
    ]

    return {
        "empty": False,
        "width": width,
        "height": height,
        "left": left,
        "right": width - right,
        "baseline": baseline,
        "bars": bars,
        "gridlines": gridlines,
    }


def supplier_bars(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Horizontal ranking: top suppliers by invoiced amount.

    Values sit at the bar tips, which replaces the x-axis entirely — direct
    labels before gridlines.
    """
    width = 720.0
    row_height = 30.0
    thickness = 18.0
    label_width = 200.0
    value_width = 96.0
    top = 8.0

    if not rows:
        return {"empty": True, "width": width, "height": 80.0}

    height = top * 2 + row_height * len(rows)
    track_start = label_width + 8.0
    track_width = width - track_start - value_width
    maximum = max(float(r["amount"]) for r in rows) or 1.0

    bars = []
    for index, row in enumerate(rows):
        amount = float(row["amount"])
        bar_width = max((amount / maximum) * track_width, 2.0)
        center = top + row_height * index + row_height / 2
        name = row["supplier"]
        bars.append(
            {
                "x": track_start,
                "y": center - thickness / 2,
                "width": bar_width,
                "height": thickness,
                "radius": min(BAR_RADIUS, thickness / 2),
                "text_y": center + 4,
                "name": name,
                "name_short": name if len(name) <= 28 else name[:27] + "…",
                "amount": amount,
                "amount_text": format_amount(amount),
                "value_text": format_compact(amount),
                "value_x": track_start + bar_width + 8,
                "count": row["invoice_count"],
            }
        )

    return {
        "empty": False,
        "width": width,
        "height": height,
        "label_width": label_width,
        "bars": bars,
    }
