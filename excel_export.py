"""Build the output Excel workbook from a list of InvoiceResult."""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from extraction import InvoiceResult

HEADERS = [
    "Archive",
    "Fichier",
    "Nom du fournisseur",
    "Numero de facture",
    "Date de la facture",
    "Montant total",
    "Devise",
    "Montant TVA",
    "Remarques",
    "Erreur",
]


def build_workbook(results: list[InvoiceResult]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Factures"

    ws.append(HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for r in results:
        ws.append(
            [
                r.archive,
                r.filename,
                r.supplier_name,
                r.invoice_number,
                r.invoice_date,
                r.total_amount,
                r.currency,
                r.vat_amount,
                r.extraction_notes,
                r.error,
            ]
        )

    widths = [30, 45, 28, 18, 16, 14, 10, 14, 40, 30]
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width

    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
