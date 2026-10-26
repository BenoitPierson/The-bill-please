"""Chart geometry for the Dashboard.

The SVG is drawn by the template, but everything numeric (scales, tick values,
bar rectangles, label positions) is computed here — Jinja is a poor place to do
arithmetic, and the geometry is the part worth keeping testable.

Mark specs follow the house data-viz rules: bars capped at 24px with a 4px
rounded data-end, a 2px surface gap between neighbours, hairline gridlines, and
labels applied selectively rather than on every mark.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence

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


def format_bytes(value: Any) -> str:
    """Human file size in French units: 845 Ko / 12,4 Mo / 1,3 Go."""
    size = float(value or 0)
    for threshold, unit in ((1024 ** 3, "Go"), (1024 ** 2, "Mo"), (1024, "Ko")):
        if size >= threshold:
            text = "{:.1f}".format(size / threshold).rstrip("0").rstrip(".")
            return "{} {}".format(text.replace(".", ","), unit)
    return "{:.0f} o".format(size)


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


def monthly_columns(
    rows: Sequence[Dict[str, Any]], current_period: Optional[str] = None
) -> Dict[str, Any]:
    """Column chart: invoiced amount per month.

    `current_period` marks the month still in progress: it is drawn lighter and
    never takes the peak label, since a half-elapsed month is not a result.
    """
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
    settled = [r for r in rows if r["period"] != current_period and float(r["amount"]) > 0]
    peak = max(settled or rows, key=lambda r: float(r["amount"]))

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
                "period": row["period"],
                "is_current": row["period"] == current_period,
                "amount": amount,
                "amount_text": format_amount(amount),
                "count": row["invoice_count"],
                # Only the peak is labelled directly; the axis carries the rest.
                "show_value": row["period"] == peak["period"] and row["period"] != current_period,
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


# Heatmap ramp, light green (nothing) to dark red (the maximum). Green->red was
# asked for; what makes it readable as a *magnitude* is that lightness falls
# monotonically along the ramp, so the grid still reads in greyscale and for a
# colour-blind reader. Values are never colour-only: every cell carries them in
# its tooltip.
HEAT_STOPS = (
    (0.00, (226, 238, 222)),
    (0.25, (196, 218, 170)),
    (0.50, (222, 196, 128)),
    (0.75, (200, 128, 92)),
    (1.00, (150, 70, 58)),
)
# Past this level the fill is dark enough that ink has to flip to white.
HEAT_DARK_FROM = 0.75


def heat_color(level: float) -> str:
    """Colour for a level in 0..1, interpolated between the ramp stops."""
    level = min(1.0, max(0.0, float(level)))
    for (low, low_rgb), (high, high_rgb) in zip(HEAT_STOPS, HEAT_STOPS[1:]):
        if level <= high:
            span = high - low
            ratio = (level - low) / span if span else 0.0
            channels = [
                int(round(low_rgb[i] + (high_rgb[i] - low_rgb[i]) * ratio)) for i in range(3)
            ]
            return "#{:02x}{:02x}{:02x}".format(*channels)
    return "#{:02x}{:02x}{:02x}".format(*HEAT_STOPS[-1][1])


def format_percent(value: float) -> str:
    """'38 %', with the narrow no-break space French typography expects."""
    return "{:.0f}{}%".format(round(float(value)), THIN_SPACE)


def day_label(day: str) -> str:
    """'2026-02-07' -> '7 fevr.'"""
    if not day or len(day) < 10:
        return day or ""
    return "{} {}".format(int(day[8:10]), MONTH_NAMES.get(day[5:7], day[5:7]))


def daily_heatmap(
    rows: Sequence[Dict[str, Any]], max_days: int = 45, max_suppliers: int = 12
) -> Dict[str, Any]:
    """Grid of (day x supplier) amounts, shaded against the grid's maximum.

    Each cell also carries what its tooltip says: the invoices behind it, the
    day's total across every supplier (hidden ones included) and the share of
    that day in the supplier's calendar month.
    """
    label_width = 168.0
    cell_width, row_height = 18.0, 22.0
    gap = 2.0  # the house 2px gap between neighbouring fills
    month_baseline, day_baseline, grid_top = 12.0, 28.0, 34.0

    entries = [
        r for r in rows
        if r.get("supplier") and r.get("day") and r.get("amount") is not None
    ]
    if not entries:
        return {"empty": True, "width": 720.0, "height": 80.0}

    day_totals: Dict[str, float] = {}
    month_totals: Dict[tuple, float] = {}
    for row in entries:
        amount = float(row["amount"])
        day_totals[row["day"]] = day_totals.get(row["day"], 0.0) + amount
        key = (row["supplier"], row["day"][:7])
        month_totals[key] = month_totals.get(key, 0.0) + amount

    totals: Dict[str, float] = {}
    for row in entries:
        totals[row["supplier"]] = totals.get(row["supplier"], 0.0) + float(row["amount"])
    ranked = sorted(totals, key=lambda name: (-totals[name], name))
    suppliers = ranked[:max_suppliers]
    kept = set(suppliers)

    all_days = sorted({r["day"] for r in entries if r["supplier"] in kept})
    days = all_days[-max_days:]  # the most recent window, read left to right
    day_index = {day: i for i, day in enumerate(days)}

    grid: Dict[tuple, Dict[str, Any]] = {}
    for row in entries:
        key = (row["supplier"], row["day"])
        if row["supplier"] not in kept or row["day"] not in day_index:
            continue
        cell = grid.setdefault(key, {"amount": 0.0, "count": 0, "numbers": []})
        cell["amount"] += float(row["amount"])
        cell["count"] += int(row.get("invoice_count") or 0)
        cell["numbers"].extend(row.get("invoice_numbers") or [])

    overall_max = max((c["amount"] for c in grid.values()), default=0.0) or 1.0

    cells = []
    for row_index, supplier in enumerate(suppliers):
        for (cell_supplier, day), cell in grid.items():
            if cell_supplier != supplier:
                continue
            amount = cell["amount"]
            month_total = month_totals.get((supplier, day[:7])) or 0.0
            cells.append(
                {
                    "x": label_width + cell_width * day_index[day] + gap / 2,
                    "y": grid_top + row_height * row_index + gap / 2,
                    "width": cell_width - gap,
                    "height": row_height - gap,
                    "fill": heat_color(amount / overall_max),
                    "supplier": supplier,
                    "day": day,
                    "date_text": day_label(day),
                    "label": "{} · {}".format(day_label(day), supplier),
                    "amount_text": format_amount(amount),
                    "count": cell["count"],
                    # Numbers are listed only while they stay readable in a tooltip.
                    "numbers": cell["numbers"] if len(cell["numbers"]) <= 3 else [],
                    "day_total_text": format_amount(day_totals.get(day, 0.0)),
                    "month_share_text": format_percent(
                        (amount / month_total * 100) if month_total else 0.0
                    ),
                }
            )

    # One month label per run of days, and day numbers only when they fit.
    months, day_ticks = [], []
    seen_month = None
    step = 1 if len(days) <= 16 else (3 if len(days) <= 40 else 5)
    for index, day in enumerate(days):
        x = label_width + cell_width * index + cell_width / 2
        if day[:7] != seen_month:
            seen_month = day[:7]
            months.append({"label": month_label(day[:7]), "x": x - cell_width / 2 + 1})
        if index % step == 0:
            day_ticks.append({"label": str(int(day[8:10])), "x": x})

    legend = [
        {
            "fill": heat_color(level),
            "abs_label": format_compact(overall_max * level),
        }
        for level in (0.0, 0.25, 0.5, 0.75, 1.0)
    ]

    return {
        "empty": False,
        "width": label_width + cell_width * len(days),
        "height": grid_top + row_height * len(suppliers) + 6,
        "label_width": label_width,
        "month_baseline": month_baseline,
        "day_baseline": day_baseline,
        "rows": [
            {
                "supplier": name,
                "name_short": name if len(name) <= 24 else name[:23] + "…",
                "text_y": grid_top + row_height * index + row_height / 2 + 4,
                "y": grid_top + row_height * index,
            }
            for index, name in enumerate(suppliers)
        ],
        "cells": cells,
        "months": months,
        "day_ticks": day_ticks,
        "legend": legend,
        "row_height": row_height,
        "max_amount": overall_max,
        "max_amount_text": format_amount(overall_max),
        "day_count": len(days),
        "supplier_count": len(suppliers),
        "hidden_suppliers": max(0, len(ranked) - len(suppliers)),
        "hidden_days": max(0, len(all_days) - len(days)),
        "first_day": days[0] if days else "",
        "last_day": days[-1] if days else "",
    }


# Scatter puts every pair of series side by side, which caps how many colours
# stay distinguishable: the house palette validates its first three slots for
# that case. Beyond three suppliers the rest folds into one grey series.
SERIES_COLORS = ("#2a78d6", "#eb6834", "#1baf7a")
OTHER_COLOR = "#898781"
MAX_SCATTER_SERIES = 3


def price_scatter(points: Sequence[Dict[str, Any]], average: Optional[float] = None) -> Dict[str, Any]:
    """Unit price over time for one product, one dot per invoice line."""
    width, height = 720.0, 300.0
    left, right, top, bottom = 68.0, 16.0, 16.0, 34.0
    plot_width = width - left - right
    plot_height = height - top - bottom
    baseline = top + plot_height

    dated = [p for p in points if p.get("date")]
    if not dated:
        return {"empty": True, "width": width, "height": height}

    prices = [float(p["price"]) for p in dated]
    maximum = nice_ceiling(max(prices) * 1.05)
    days = sorted({p["date"] for p in dated})
    first, last = days[0], days[-1]
    span = max(1, _days_between(first, last))

    # Suppliers keep their colour whatever the current filter shows: the order
    # is by volume, and the entity — not its rank in this view — carries it.
    counts: Dict[str, int] = {}
    for point in dated:
        counts[point["supplier"]] = counts.get(point["supplier"], 0) + 1
    ranked = sorted(counts, key=lambda name: (-counts[name], name))
    colors = {name: SERIES_COLORS[i] for i, name in enumerate(ranked[:MAX_SCATTER_SERIES])}

    dots = []
    for point in dated:
        offset = _days_between(first, point["date"])
        price = float(point["price"])
        dots.append({
            "cx": left + (offset / span) * plot_width if span else left + plot_width / 2,
            "cy": baseline - (price / maximum) * plot_height if maximum else baseline,
            "color": colors.get(point["supplier"], OTHER_COLOR),
            "supplier": point["supplier"],
            "date": point["date"],
            "label": "{} · {}".format(day_label(point["date"]), point["supplier"]),
            "value": "{} {} / {}".format(
                format_amount(price), point.get("currency") or "", point.get("unit_label") or ""
            ).strip(),
        })

    gridlines = [
        {"y": baseline - (value / maximum) * plot_height, "label": format_compact(value)}
        for value in _ticks(maximum)
    ]
    legend = [{"name": name, "color": colors[name], "count": counts[name]} for name in colors]
    if len(ranked) > MAX_SCATTER_SERIES:
        legend.append({
            "name": "{} autres fournisseurs".format(len(ranked) - MAX_SCATTER_SERIES),
            "color": OTHER_COLOR,
            "count": sum(counts[name] for name in ranked[MAX_SCATTER_SERIES:]),
        })

    return {
        "empty": False,
        "width": width,
        "height": height,
        "left": left,
        "right": width - right,
        "baseline": baseline,
        "dots": dots,
        "gridlines": gridlines,
        "legend": legend,
        "average_y": baseline - (average / maximum) * plot_height if average and maximum else None,
        "average_text": format_amount(average) if average else "",
        "first_label": day_label(first),
        "last_label": day_label(last),
        "point_count": len(dots),
    }


def _days_between(first: str, second: str) -> int:
    """Whole days between two YYYY-MM-DD dates; 0 if either is unusable."""
    try:
        start = date(int(first[:4]), int(first[5:7]), int(first[8:10]))
        end = date(int(second[:4]), int(second[5:7]), int(second[8:10]))
    except (TypeError, ValueError, IndexError):
        return 0
    return (end - start).days


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
