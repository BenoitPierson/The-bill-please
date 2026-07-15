# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local web tool that extracts structured data from invoices (PDF or photos, printed or
handwritten, French or English) using Claude's vision API, and outputs an Excel file with one
row per invoice: supplier name, invoice number, date, total amount, VAT amount.

## Commands

```
.venv\Scripts\activate
python app.py
```

Runs the FastAPI app with `uvicorn` (auto-reload on file changes) at http://127.0.0.1:8000.
Double-clicking `Lancer.bat` (or the desktop shortcut) does the same and opens the browser
automatically.

There is no test suite, linter, or build step configured.

To reinstall dependencies from scratch:

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

The venv was built against Anaconda Python 3.8.8 — see the "Python 3.8 compatibility"
note below before adding new type hints.

## Architecture

Three modules, no framework beyond FastAPI:

- **`extraction.py`** — all Claude API logic. Converts an uploaded file into one or more
  page images (`file_to_page_images`: PDFs are rasterized page-by-page with PyMuPDF at
  `PDF_RENDER_DPI`; photos are passed through, downscaled if above `MAX_IMAGE_LONG_EDGE`),
  sends them in a single Messages API request with a JSON-schema structured output
  (`INVOICE_SCHEMA`), and parses the response into an `InvoiceResult` dataclass. One call to
  `extract_invoice` = one invoice, all its pages sent together (so multi-page totals/VAT
  recap tables are seen in context). Errors (unreadable file, API failure, refusal, bad JSON)
  are caught per-file and stored on `InvoiceResult.error` rather than raised, so one bad
  invoice never aborts a batch.
- **`excel_export.py`** — turns a `list[InvoiceResult]` into an `.xlsx` byte string
  (`openpyxl`, in-memory `BytesIO`, no disk writes).
- **`app.py`** — FastAPI app with two routes: `GET /` serves `templates/index.html`
  (a single-page drag & drop UI, no JS framework, no build step) and `POST /process` accepts
  multipart file uploads, runs each through `extraction.process_upload`, and streams back the
  generated Excel file as the HTTP response (no persistence — nothing is written to disk on
  the server side).

Request flow: browser drag&drop → `POST /process` (multipart) → per-file
`file_to_page_images` → `extract_invoice` (one Claude API call per invoice) → collected into
`InvoiceResult` list → `build_workbook` → `.xlsx` streamed back → browser triggers download.

### Claude API integration details

- Model is pinned in `extraction.py::MODEL` (`claude-sonnet-5`).
- Thinking is explicitly disabled (`thinking={"type": "disabled"}`) — this is a
  single-shot extraction task, not a reasoning task, and keeps `max_tokens` budget
  predictable.
- **Structured output goes through `extra_body`, not the typed `output_config` kwarg.**
  The pinned `anthropic` SDK version (0.72.0, latest on PyPI as of this writing) does not
  expose `output_config` as a named parameter on `messages.create()` yet. Passing
  `extra_body={"output_config": {...}}` forwards it as raw JSON in the request body, which
  the API accepts. If the SDK is upgraded and gains native `output_config` support, this can
  be simplified back to a normal kwarg — check `inspect.signature(Messages.create)` first.
- The invoice/page images are base64-encoded inline in the request (no Files API).

### Python 3.8 compatibility

The venv runs Anaconda Python 3.8.8. `from __future__ import annotations` is used everywhere
so `X | None` and bare `list[...]`/`tuple[...]` generics are safe *as long as nothing
evaluates them at runtime*. FastAPI/Pydantic **does** evaluate route handler signatures at
import time (to build request/response models), so PEP 585/604 syntax (`list[X]`, `X | None`)
in `app.py` route function signatures will raise `TypeError: 'type' object is not
subscriptable` on 3.8 — use `typing.List[X]` / `typing.Optional[X]` there instead. Plain
dataclasses and non-route functions (e.g. everything in `extraction.py`) are unaffected since
their annotations are never evaluated.

## Key assumptions baked into the code

- One uploaded file = one invoice (a multi-page PDF is one invoice's pages, not multiple
  invoices in one file).
- The supplier is the invoice's issuer, not the client/recipient — this distinction is
  spelled out in `SYSTEM_PROMPT` because it's the most common extraction mistake.
- Amounts are normalized to plain numbers with `.` as decimal separator (European
  `1 234,56` → `1234.56`) and dates to `YYYY-MM-DD` when unambiguous — both are instructed
  in `SYSTEM_PROMPT`, not post-processed in Python.
- `MAX_PAGES_PER_INVOICE` (5) caps how many PDF pages are sent per invoice, to bound cost.
