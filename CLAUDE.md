# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A local web tool that extracts structured data from invoices (PDF or photos, printed or
handwritten, French or English) using Claude's vision API, and outputs an Excel file with one
row per invoice: supplier name, invoice number, date, total amount, VAT amount. Invoices can
be dropped individually or as `.zip` archives holding hundreds of them.

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

- **`extraction.py`** — archive expansion + all Claude API logic. `expand_upload` turns one
  upload into a list of `InvoiceSource` (a `.pdf`/image yields one; a `.zip` yields one per
  document inside, recursing into nested archives up to `MAX_ARCHIVE_DEPTH`). An
  `InvoiceSource` holds its bytes *lazily* — archive members are read only when a worker
  picks them up, so a 300 MB archive is never fully decompressed in memory; the shared
  `archive_bytes` is immutable, and each read wraps it in a fresh `ZipFile` because zipfile
  handles are not thread-safe. Then `file_to_page_images` converts a document into page
  images (PDFs rasterized page-by-page with PyMuPDF at `PDF_RENDER_DPI`; photos passed
  through, downscaled above `MAX_IMAGE_LONG_EDGE`), and `extract_invoice` sends them in a
  single Messages API request with a JSON-schema structured output (`INVOICE_SCHEMA`). One
  call to `extract_invoice` = one invoice, all its pages sent together (so multi-page
  totals/VAT recap tables are seen in context). Errors (unreadable file, API failure,
  refusal, bad JSON, unsupported archive member) are caught per-file and stored on
  `InvoiceResult.error` rather than raised, so one bad invoice never aborts a batch.
- **`excel_export.py`** — turns a `list[InvoiceResult]` into an `.xlsx` byte string
  (`openpyxl`, in-memory `BytesIO`, no disk writes).
- **`app.py`** — FastAPI app with two routes: `GET /` serves `templates/index.html`
  (a single-page drag & drop UI, no JS framework, no build step) and `POST /process` accepts
  multipart file uploads, expands them into invoice sources, extracts them concurrently
  (`_process_all`), and streams back the generated Excel file as the HTTP response.

Request flow: browser drag&drop → `POST /process` (multipart) → `expand_upload` per upload
(archives fan out into many sources) → `_process_all` runs `process_source` across a
`ThreadPoolExecutor` → per source `file_to_page_images` → `extract_invoice` (one Claude API
call per invoice) → results reordered to match input → `build_workbook` → `.xlsx` streamed
back → browser triggers download.

### Concurrency

A single archive can hold hundreds of invoices (the reference dataset has ~1180 across 7
archives), and each invoice is a separate API round-trip of a few seconds — sequential
processing would take hours. `_process_all` fans the work out over a `ThreadPoolExecutor`
capped at `MAX_CONCURRENT_EXTRACTIONS` (8), which the SDK's retry logic keeps within API
rate limits. Two constraints shape this design:

- The whole batch runs via `loop.run_in_executor` so the blocking work (HTTP + PDF
  rendering) never freezes the event loop.
- Results are written back into a pre-sized list by index, so Excel row order matches
  upload order regardless of completion order.

Progress is logged to the server console (`logger.info`, every 10 invoices) — the HTTP
response only arrives when the entire batch is done, so that log is the only live feedback.
A long batch therefore means a single long-running request; if this becomes a problem
(browser/proxy timeouts, no resumability), the next step is a job queue with a polling
endpoint rather than a bigger thread pool.

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

- One document = one invoice (a multi-page PDF is one invoice's pages, not several invoices
  in one file). Real data does violate this occasionally — the model flags it in
  `extraction_notes` rather than splitting, and only the first invoice's data is returned.
- The supplier is the invoice's issuer, not the client/recipient — this distinction is
  spelled out in `SYSTEM_PROMPT` because it's the most common extraction mistake. The
  supplier folder name inside an archive is *not* used as a hint; extraction relies on the
  document alone.
- `invoice_number` must come from an INVOICE NUMBER / CV INVOICE NUMBER field, never from a
  RECEIPT NUMBER — both appear on the reference dataset's invoices.
- Amounts are normalized to plain numbers with `.` as decimal separator (European
  `1 234,56` → `1234.56`) and dates *always* to `YYYY-MM-DD` (ambiguous day/month order is
  resolved from context and flagged in `extraction_notes`, never left in the source format)
  — both are instructed in `SYSTEM_PROMPT`, not post-processed in Python.
- `MAX_PAGES_PER_INVOICE` (5) caps how many PDF pages are sent per invoice, to bound cost.
- Archive members that are neither documents nor known OS junk (`__MACOSX/`, dotfiles,
  `Thumbs.db`) are reported as error rows rather than silently dropped, so nothing vanishes
  from the report without explanation.
