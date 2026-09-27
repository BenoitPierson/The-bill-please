# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A multi-tenant web platform that extracts structured data from invoices (PDF or photos,
printed or handwritten, French or English) using Claude's vision API. Two working tabs:
**Dashboard** (aggregates) and **Invoices** (a reviewable, editable, exportable table).
Invoices are imported individually or as `.zip` archives holding hundreds of them.

## Commands

```
Lancer.bat                       # start locally (also opens the browser)
.venv\Scripts\python.exe app.py  # same, without the browser

python manage.py tenants                            # list client workspaces (+ storage, quota)
python manage.py add-tenant acme --name "ACME SARL" # provision a client
python manage.py add-user acme compta@acme.fr       # create an account
python manage.py storage acme                       # storage breakdown for one client
python manage.py set-quota acme 5000                # storage cap in MB, 0 = unlimited
```

There is no test suite in the repo, no linter, no build step. The front end is
server-rendered Jinja + one CSS file + one JS file, deliberately without a bundler.

**Running Python outside `Lancer.bat` needs Anaconda's DLL directories on PATH**, or
`import sqlite3` / `import ssl` fail with "DLL load failed" (see Python 3.8 note below):

```powershell
$conda = "$env:USERPROFILE\anaconda3"
$env:PATH = "$conda;$conda\Library\bin;$conda\Scripts;$env:PATH"
```

## Architecture

Request flow: browser → tenant resolved from the `Host` header → session checked against
that tenant → per-tenant SQLite database and file directory.

| Module | Responsibility |
|---|---|
| `config.py` | Settings from the environment; generates/persists a local session secret |
| `tenants.py` | Tenant registry (the filesystem *is* the registry) and Host → tenant resolution |
| `db.py` | Per-tenant schema, connections, queries, dashboard aggregates |
| `auth.py` | scrypt password hashing (stdlib — no native dep to build on Windows) |
| `extraction.py` | Archive expansion + the Claude call that turns a document into fields |
| `pipeline.py` | Background import: expand → store original → extract concurrently → persist |
| `learning.py` | User corrections → generalised extraction rules |
| `charts.py` | Dashboard chart geometry (scales, ticks, bar rectangles) |
| `excel_export.py` | Excel export of the filtered table, with the review colour code |
| `app.py` | FastAPI routes, templates, session middleware |

### Multi-tenancy: isolation by construction

Each client gets `DATA_DIR/tenants/<slug>/` containing `data.db` and `files/`. There is **no
shared table and no `tenant_id` column** — a query can only see the database it was opened
on, so cross-tenant leakage is not a bug you can write. It also makes per-client backup,
export and GDPR deletion a directory operation.

The trade-off is that schema changes must run against every tenant database. `db.connect()`
runs `SCHEMA` plus `_migrate()` once per database per process (guarded by `_initialised`,
since an import opens thousands of connections from parallel threads). `SCHEMA` only covers
*new* databases — `CREATE TABLE IF NOT EXISTS` never alters an existing table — so a column
added later must **also** be listed in `MIGRATIONS`, which `ALTER TABLE ADD COLUMN`s it into
existing ones. Keep migrations additive. An index on a migrated column belongs in
`_migrate()`, not `SCHEMA`, because on an old database the column does not exist yet when
`SCHEMA` runs.

Tenant resolution (`tenants.resolve_from_host`) needs `APP_DOMAIN` in production: without it,
nothing distinguishes `acme.factures.example.com` (tenant "acme") from the bare application
domain `factures.example.com`. Locally, any non-localhost host falls back to `DEFAULT_TENANT`.
Only `DEFAULT_TENANT` is auto-created; an unknown subdomain must 404 rather than silently
provision an empty workspace.

Sessions are signed cookies carrying `{tenant, email}`. `current_user()` refuses a session
whose tenant does not match the host, so a cookie cannot be replayed against another client.

### Import pipeline & concurrency

A batch can hold ~1180 invoices (the reference dataset), each a separate API round-trip of a
few seconds. `pipeline.start_import` therefore returns immediately with a `batch_id` and runs
the work in a background thread; the browser polls `/api/batches/{id}`. Inside, a
`ThreadPoolExecutor` capped at `MAX_CONCURRENT_EXTRACTIONS` (8) keeps within API rate limits,
and `_running_imports` prevents a second concurrent batch per tenant (which would multiply
effective concurrency).

Measured on 24 real invoices (8 workers): ~10 s per invoice for one worker, of which ~71% is
the Claude call and ~14% PDF rendering; 1.58 s per invoice of wall time in a batch, i.e.
~31 min for the 1181-invoice reference set. Eight fully independent workers would give
1.25 s — the gap is contention, mostly concurrent SQLite writes (an insert is 0.06 s median
but up to 3 s under load).

**Remaining-time estimate.** `pipeline.estimate_remaining` feeds the countdown shown during
an import (via `/api/batches/{id}`, fields `eta_seconds`, `eta_basis`, `elapsed_seconds`).
Until one full round of workers has finished it uses the measured prior
(`ESTIMATED_SECONDS_PER_INVOICE` × `BATCH_CONTENTION`, per round of workers); after that it
follows observed wall time per extraction. Only documents that actually went through
extraction are timed (`_BatchState.record_extraction`): duplicates take milliseconds and
would make the estimate absurdly optimistic, so the duplicate share seen so far is applied to
the remaining documents instead. The live state lives in `_active_batches` and is registered
in `start_import` *before* the thread starts — otherwise an immediate poll would find no
state and wrongly declare the batch orphaned. A batch the database marks `running` but that
this process is not running (server restarted mid-import) is marked `interrupted` by
`app._reconcile_batch`; re-uploading resumes it, since deduplication skips what was done.

**Import summary pop-up.** When a batch ends, `app.js` fetches `/api/batches/{id}/summary`
(409 while still running) and shows the modal defined in `base.html`. `db.batch_summary`
counts from the rows the batch actually wrote (`invoices` + `duplicates`), not from the
`batches` counters, and derives `not_processed` from the difference with `total` — that is
what an interrupted batch reports. Failures are grouped by `db.error_kind`, which matches
the opening words of the error messages written in `extraction.py` / `pipeline.py`: **a new
error message needs its prefix added to `ERROR_KINDS`**, or it lands in "other". The summary
must survive the user leaving the page mid-import, so it is re-offered on page load
(`pending_summary_batch`, scoped to `started_by`) until closed (`/ack` sets
`acknowledged_at`); the migration marks pre-existing batches acknowledged so they don't pop
up after an upgrade. Links in the summary use the `batch` filter of `/invoices`.

One catch worth keeping in mind: a summary link pointing at an **anchor of the page already
shown** (`/invoices#doublons`) does nothing on its own — the browser jumps without reloading,
so the modal stays up and the panel never opens. Such links carry `data-summary-anchor`, and
the handler acknowledges the batch, waits for that to land (a reload would race it and bring
the pop-up straight back), then reloads onto the anchor, where `openDuplicates` opens the
panel with the rows the import just added.

`InvoiceSource` holds archive bytes lazily: members are read only when a worker picks them
up, so a 300 MB archive is never fully decompressed in memory. The shared `archive_bytes` is
immutable and each read wraps it in a fresh `ZipFile`, because zipfile handles are not
thread-safe.

Originals are written to `tenants/<slug>/files/<invoice_id><ext>` and served by
`/invoices/{id}/file`, which re-resolves the path inside the tenant directory and verifies
containment before serving — never a static mount, since these are client documents behind
authentication.

### Deduplication & storage

Every document is fingerprinted (SHA-256 of its bytes) in `pipeline._process_one` *before*
it is stored or sent to Claude. On the reference dataset 39 of 1181 files are exact copies —
several are the same invoice filed in two monthly archives — which would otherwise be stored
twice, extracted (paid) twice, and **counted twice in the Dashboard totals**. That last point
is why this is a correctness feature, not just a storage one. A skipped copy is logged in the
`duplicates` table (shown on the Invoices page) rather than silently dropped.

Three rules to preserve:

- **Check-and-claim is atomic.** `_BatchState.lock` covers both the lookup and the claim,
  and `claimed` tracks fingerprints *within* the batch: the database only learns about the
  first copy after its extraction finishes, so without the in-memory set two parallel
  workers holding the same document would both import it.
- **A failed import is retryable.** If the matching row has an `error` and no hand edits,
  re-importing replaces it (`_can_retry`) — otherwise an API overload would become a
  permanent failure. A row the user has edited is never replaced.
- Invoices imported before fingerprints existed are hashed from their stored file by
  `_backfill_fingerprints` when the column is first added, so they are recognised too.

Storage is measured on disk (`tenants.storage_usage`: originals + SQLite files including
`-wal`/`-shm`), not summed from `file_size`, so files orphaned by an interrupted import still
count. The quota (`tenant.json` `storage_quota_mb`, else `DEFAULT_STORAGE_QUOTA_MB`, 0 =
unlimited) is enforced twice: `start_import` refuses a batch when already full, and each
worker checks the running total in `_BatchState.used_bytes` so a large batch stops at the cap
instead of overshooting it. A refused file becomes an error row.

Measured on the reference dataset: ~1.1 MB per invoice on average but a heavy tail (files
over 5 MB are 2% of documents and 23% of volume), ~2 GB per client per year. Lossless PDF
recompression gains nothing (they are scans); lossy re-rendering gains ~85% but is
deliberately **not** applied — it may void the document's status as a faithful copy for
legal retention, which is a product decision, not a technical one.

### The correction → rule loop

This is the part worth understanding before changing it. A raw correction
(`invoice_number: 0190485190000003873 → BC-2026-0211`) is a *value*, and values don't
generalise. `learning.py` therefore sends the pending corrections for a supplier to Claude
and asks for the **rule** behind them ("don't use the long number near the barcode; take the
alphanumeric reference"). Rules are stored one per supplier (plus one global), *refined* on
each run rather than appended, so the prompt stays small however long the tool is used.

`rules_for_prompt()` injects **all** of a tenant's rules into every extraction, because the
supplier is only known *after* extraction — there is no way to select the right rule
beforehand. They go in the `system` prompt (instructions), not in the user message that
carries the images.

The cost of that is real and worth knowing before raising `MAX_RULES_IN_PROMPT` (60):
measured with `count_tokens`, the base system prompt is ~1270 tokens, ~1850 with 5 rules,
~6900 with 60 — against ~2900 tokens for the invoice image itself. At the cap, the rules
would more than double the per-invoice input.

This is why the system block carries `cache_control` in `extract_invoice`: it is
byte-identical across every invoice of a batch (rules are loaded once in `_run_batch`), while
the images differ — the shared-prefix case. Verified on real calls: ~2500 tokens written to
cache on the first request, then re-read at ~0.1x on every subsequent one, worth roughly $7
on a 1180-invoice batch. The first few concurrent workers necessarily miss the cache (nothing
is written yet), which is negligible at batch scale.

If the rule set still outgrows this, the alternative is to stop sending all of them: the
archive folder name is a usable supplier hint *before* extraction (the reference dataset
stores invoices under `<month>/<supplier>/`), so rules could be selected per invoice.

Learning is triggered automatically once `AUTO_LEARN_THRESHOLD` corrections are pending, and
manually from the Invoices panel. Corrections are marked `learned` either way — including
those too vague to yield a rule — so they are not re-analysed on every run.

### Claude API integration

- Model pinned in `extraction.py::MODEL` (`claude-sonnet-5`); rule distillation uses
  `learning.py::RULE_MODEL`.
- Thinking is explicitly disabled — single-shot extraction, not a reasoning task, and it
  keeps the `max_tokens` budget predictable.
- **Structured output goes through `extra_body`, not the typed `output_config` kwarg.** The
  pinned `anthropic` SDK (0.72.0) does not expose `output_config` on `messages.create()`;
  `extra_body` forwards it as raw JSON, which the API accepts. If the SDK gains native
  support, simplify it back — check `inspect.signature(Messages.create)` first.
- `uncertain_fields` in `INVOICE_SCHEMA` is what drives the orange highlighting. It is a
  structured array of field names rather than prose, precisely so the UI can act on it;
  `extraction_notes` carries the human-readable explanation alongside.
- Client is built with `max_retries=6`: the default of 2 was not enough to ride out 529
  "overloaded" spikes, which silently left invoices unprocessed.

### Charts

`charts.py` computes geometry; the template only draws. House data-viz rules are applied:
bars capped at 24px with a 4px rounded data-end squared at the baseline (the `bar-foot` rect),
hairline gridlines, axis bounds rounded to readable values (`nice_ceiling`), and labels used
selectively — the monthly chart labels only its peak, the supplier ranking labels every tip
and drops the axis entirely. Both charts are single-series, so no legend.

The UI commits to a single light theme on purpose (`color-scheme: light`); there is no dark
variant to keep in sync.

**Heatmap (day × supplier).** `daily_heatmap` computes *both* fills per cell — absolute
(share of the grid's maximum) and relative (share of that supplier's own busiest day) — and
the toggle in `app.js` swaps `data-fill-abs` / `data-fill-rel` without a reload. Green→red
was a product request; it works as a magnitude ramp only because `HEAT_STOPS` also falls
monotonically in lightness, which is what keeps it readable in greyscale and for a
colour-blind reader — **check that property if you touch the stops** (the test suite does).
Colour is never the sole channel: each cell carries its value in an SVG `<title>` and in the
hover tooltip. The grid is capped (12 suppliers, 45 most recent days) and says what it hid;
it scrolls sideways rather than shrinking cells below a readable size.

**Amounts are summed as stored, across currencies.** `dashboard_stats` returns a currency
breakdown and the template warns when more than one is present — do not add a total that
silently mixes currencies. The extraction prompt normalises currencies to ISO 4217 codes
specifically so this stays rare.

### Products tab: per-product cost drift

Line items are extracted alongside the header fields (`lines` in `INVOICE_SCHEMA`) and stored
in `invoice_lines`, one row per billed article. Three decisions hold the feature together:

- **`product_key` is the whole point.** The model returns a generic French name — no brand,
  no packaging, no grade — so supplier A's "Red Tomatoes 5kg" and supplier B's "Tomatoes"
  collapse onto `tomate`. Ordering by (category, `product_key`) is what the user means by
  *semantic* rather than alphabetical order: the same goods end up adjacent whatever each
  supplier calls them. `label` keeps the printed wording for the table.
- **The unit is part of the grouping key** (product + supplier + unit + currency). 2 EUR/kg
  and 2 EUR/carton are not comparable, and merging them invents price drifts that are really
  packaging differences.
- **Nothing relies on the model answering identically twice.** It does not: the same printed
  line came back as `frites`/`piece` and `frite`/`carton`, splitting one product into three
  rows. `canonical()` folds case, accents, punctuation, plurals and elided articles, and
  `_resolve_variants` lets every line sharing a supplier + printed label vote on one key and
  one unit — the label is on the document, the key and unit are only the model's reading of
  it. A group whose unit was read inconsistently is flagged in the table rather than silently
  resolved.
- **Supplier spellings are merged conservatively.** `resolve_suppliers` drops legal forms
  ("LIMITED", "SARL"…) and merges two names only when one's remaining words are a subset of
  the other's: `FRESHCHIPS LIMITED` ⊂ `FRESHCHIPS PROCESSORS LIMITED` merges, `Bidco Foods`
  vs `Bidco Oil` does not. One-letter words are kept here (unlike `canonical`), or
  "Fournisseur A" and "Fournisseur B" would collapse into one. Comparing suppliers is the
  point of the tab, so a wrong merge is worse than two rows. **This applies to the Products
  tab only** — Dashboard, Invoices and the filters still show the extracted name verbatim.
- **The alert threshold is a reading choice, not a query.** Each row carries its `drift`
  (how far max sits above the average, in percent); the slider repaints client-side and
  writes itself into the forms' hidden `threshold`, so filtering keeps the setting.
- **A price points back at its invoice.** `minimum_ref` / `maximum_ref` carry the invoice
  behind the extreme (the most recent one when several share that price), which the table
  shows in the cell tooltip and links to `/invoices/{id}/file`. An alert is only actionable
  if the document is one click away.

`products.summarise` is a pure function over raw rows — no DB — which is why the statistics
are unit-tested directly. `db.product_lines` deliberately returns raw lines rather than
SQL aggregates: picking the most frequent wording and category per group is trivial in
Python and awkward in SQLite, and the same rows feed the price-history scatter.

**Line extraction only applies to imports made after it shipped**, and deduplication blocks
re-importing the same files, so backfilling an existing corpus needs a re-extraction pass
(not built — it was declined as out of scope; it would re-read stored originals and replace
the rows). The empty state on the tab says so.

`max_tokens` had to go from 2048 to 8192: a 40-line invoice truncates otherwise, and a
truncated JSON is a failed extraction. This costs real money on output tokens — roughly
half a cent to a cent per invoice — so do not add verbose fields to the schema lightly.

### UI conventions (product decisions)

- User-facing text never names the model: say **"l'automate"**, not "Claude" (code, comments
  and this file may).
- All buttons share one colour; `.btn-primary` only makes the label heavier. Blue is kept
  for links and focus, not button fills.
- The document viewer (`#docModal`) shows the original beside its editable fields, because
  opening a document is mostly done to check what was extracted. It loads fields from
  `GET /api/invoices/{id}` and saves through the same `saveField` path as the table cells
  (so corrections still feed the learning loop), then syncs the table row. Saves are tied to
  the invoice id captured when the field was focused: moving to the next invoice while an
  edit is pending must not write it onto the new one.

### Security invariants

Checked by the security suite; breaking one of these is a vulnerability, not a regression.

- **Never render user-controlled text as HTML.** Supplier names and extraction notes come
  off documents an outsider can send, so `innerHTML` with them is stored XSS. Build nodes and
  set `textContent` (the chart tooltip and the summary pop-up do). The CSP
  (`script-src 'self'`, no inline) is the second line of defence — keep scripts external.
- **Stored file names are derived from the invoice id, never from the upload.** A filename
  (upload or archive member) is attacker-controlled and its "extension" can carry
  `../`; `_store_original` accepts only `^\.[a-z0-9]{1,8}$` and verifies containment.
  `/invoices/{id}/file` re-verifies containment and serves only `VIEWABLE_TYPES` inline —
  an HTML/SVG "invoice" must never come back as `text/html` on this origin.
- **Session = tenant + account.** `current_user` refuses a cookie whose tenant is not the
  host's *and* one whose account no longer exists; `/login` clears the session before
  setting it, and `auth` locks an email+IP after `FAILURES_BEFORE_LOCK` failures.
- **Framing is `'self'`, never `'none'`.** The document viewer iframes the original from this
  same origin, and `X-Frame-Options: DENY` / `frame-ancestors 'none'` breaks it — Firefox
  refuses even a same-origin frame. `SAMEORIGIN` / `'self'` still blocks clickjacking from
  another site, which is the point of the header.
- **Cookies are `Secure` as soon as `APP_DOMAIN` is set** (`SESSION_HTTPS_ONLY` overrides).
  `same_site="lax"` is what stands in for CSRF tokens — do not widen it to "none".
- **Uploads are capped** (`MAX_UPLOAD_MB`): the request body is held in memory while it is
  expanded, so an uncapped upload is a denial of service for every tenant on the box.

### Static assets & browser cache

`StaticFiles` sends no `Cache-Control`, so browsers cache `app.js`/`app.css` heuristically
and kept running the old script after an update (the import summary never appeared). Always
reference assets through the `static_url('app.js')` template global, which appends the
file's mtime as `?v=` — never a bare `/static/...` URL.

### CSS trap

A `display` rule in a component class silently beats the browser default for `[hidden]`, so
JS-toggled panels stay visible. `app.css` has a global `[hidden] { display: none !important }`
for this — keep it.

### Python 3.8 compatibility

The venv runs Anaconda Python 3.8.8. `from __future__ import annotations` is used everywhere,
so `X | None` and bare `list[...]` generics are safe *as long as nothing evaluates them at
runtime*. FastAPI/Pydantic **does** evaluate route handler signatures at import time, so PEP
585/604 syntax in `app.py` route signatures raises `TypeError: 'type' object is not
subscriptable` — use `typing.List[X]` / `typing.Optional[X]` there. Plain dataclasses and
non-route functions are unaffected.

`Installer.bat` sets a new machine up (find a real Python — `where python` alone would match
the Microsoft Store stub, so each candidate is executed to prove it works — create `.venv`,
install `requirements.txt`, create `.env` from the example). `Mettre a jour.bat` pulls and
reinstalls if needed. `Lancer.bat` refuses to start without `.venv`/`.env` and points at the
installer, so a non-technical user is never left with a window that closes instantly.

`Lancer.bat` prepends Anaconda's DLL directories to `PATH` **when that folder exists**;
without them `_ssl` and `_sqlite3` fail to load when launched from Explorer on this machine,
but a poste installed from python.org has no such folder and must not get those entries. It also frees port 8000 from a stale instance
(error 10048) and waits for the server to answer before opening the browser
(`open_browser.bat`, using `curl` rather than PowerShell to avoid execution-policy issues).
Uvicorn auto-reload stays **off**: it watches `.venv` and hangs startup on Windows.

## Key assumptions baked into the code

- One document = one invoice. Real data violates this occasionally — the model flags it in
  `extraction_notes` and returns the first invoice rather than splitting.
- The supplier is the invoice's issuer, not the client. The supplier folder name inside an
  archive is *not* used as a hint; extraction relies on the document alone.
- `invoice_number` comes from an INVOICE NUMBER / CV INVOICE NUMBER field, never a RECEIPT
  NUMBER, and never the long KRA/control number printed near the barcode on the reference
  dataset's Kenyan invoices.
- Dates always `YYYY-MM-DD`, currencies always ISO 4217, amounts always plain numbers — all
  instructed in `SYSTEM_PROMPT`, not post-processed in Python.
- `EDITABLE_FIELDS` in `db.py` is the authority on what a user may change; provenance
  (filename, archive, ids) is never editable, and `update_invoice_field` refuses anything
  outside it.
- Archive members that are neither documents nor known OS junk are reported as error rows
  rather than silently dropped.
