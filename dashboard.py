"""Pure calculations behind the home page (no database, no I/O).

Kept apart from db.py and app.py so the date and currency rules — which month
the big figure covers, which currency it is expressed in, which price alerts
make the cut — are testable on their own.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

MONTHS_FR = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def period(year: int, month: int) -> str:
    """'2026-09' — the YYYY-MM prefix invoice dates are grouped on."""
    return "{:04d}-{:02d}".format(year, month)


def last_complete_month(today: date) -> Tuple[int, int]:
    """The calendar month before the current one: the current month is never complete."""
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def month_window(today: date, months: int = 12) -> List[str]:
    """The last `months` periods, oldest first, ending with the current month."""
    index = today.year * 12 + (today.month - 1)
    return [period(i // 12, i % 12 + 1) for i in range(index - months + 1, index + 1)]


def month_name(year: int, month: int) -> str:
    """'septembre 2026'."""
    return "{} {}".format(MONTHS_FR[month - 1], year)


def main_currency(rows: Sequence[Dict[str, Any]]) -> Optional[str]:
    """The currency most invoices are in; ties go to the larger amount, then the name.

    An unknown currency ("") only wins when nothing else is known: showing a
    real currency is more useful than a blank one.
    """
    if not rows:
        return None
    known = [r for r in rows if r.get("currency")] or list(rows)
    best = min(
        known,
        key=lambda r: (-int(r.get("invoice_count") or 0), -float(r.get("amount") or 0.0), r.get("currency") or ""),
    )
    return best.get("currency") or ""


def top_price_alerts(summary: Sequence[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    """The strongest price rises already flagged by products.summarise."""
    alerts = [row for row in summary if row.get("alert")]
    alerts.sort(key=lambda row: -float(row.get("drift") or 0.0))
    return alerts[:limit]
