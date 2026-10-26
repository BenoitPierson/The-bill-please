"""Multi-tenant invoice extraction platform.

Each client company is served on its own subdomain and gets its own database
and file storage (see tenants.py). Two working tabs: Dashboard (aggregates)
and Invoices (the reviewable, editable, exportable table).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlencode
from typing import Any, Dict, List, Optional, Tuple

from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

import auth
import charts
import dashboard as homepage
import db
import documents
import learning
import pipeline
import products
import tenants
from config import (
    AUTO_LEARN_THRESHOLD,
    BASE_DIR,
    DEFAULT_TENANT,
    MAX_UPLOAD_MB,
    SESSION_COOKIE,
    SESSION_HTTPS_ONLY,
    SESSION_MAX_AGE,
    session_secret,
)
from excel_export import build_workbook

load_dotenv()

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="Extraction de factures")
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret(),
    session_cookie=SESSION_COOKIE,
    max_age=SESSION_MAX_AGE,
    # "lax" keeps the cookie off cross-site POST/PATCH/DELETE, which is what
    # stands in for CSRF tokens here; the API is only reachable same-origin.
    same_site="lax",
    https_only=SESSION_HTTPS_ONLY,
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Baseline hardening for every response.

    The CSP is the real one: it forbids inline and third-party scripts, so a
    value that slipped through escaping somewhere cannot execute.

    Framing is 'self', not 'none': the document viewer shows the original
    invoice in an iframe served by this same origin, and a blanket DENY breaks
    it (Firefox refuses even a same-origin frame). Another site still cannot
    frame the application, which is what the clickjacking rule is about.
    """
    response = await call_next(request)
    response.headers.setdefault(
        "Content-Security-Policy",
        # 'unsafe-inline' applies to styles only, for the style="" attributes
        # that carry chart geometry; scripts stay strictly external.
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "object-src 'self'; frame-src 'self'; frame-ancestors 'self'; base-uri 'none'; "
        "form-action 'self'",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    # Client invoices must never be cached by a proxy on the way.
    if request.url.path.startswith(("/invoices", "/api", "/dashboard")):
        response.headers.setdefault("Cache-Control", "no-store, private")
    return response

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["amount"] = charts.format_amount
templates.env.filters["compact"] = charts.format_compact
templates.env.filters["filesize"] = charts.format_bytes


def static_url(name: str) -> str:
    """Static asset URL carrying the file's modification time.

    StaticFiles sends no Cache-Control, so browsers cache app.js/app.css
    heuristically and keep running the old version after an update. A changed
    file gets a new URL, which the browser has to fetch.
    """
    try:
        version = int((BASE_DIR / "static" / name).stat().st_mtime)
    except OSError:
        version = 0
    return "/static/{}?v={}".format(name, version)


templates.env.globals["static_url"] = static_url

_client: Optional[Anthropic] = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        # The SDK retries 429/5xx (including 529 "overloaded") with exponential
        # backoff; 6 attempts rides out the API load spikes seen in practice.
        _client = Anthropic(max_retries=6)
    return _client


# --------------------------------------------------------------------- tenant + auth


def current_tenant(request: Request) -> Optional[str]:
    slug = tenants.resolve_from_host(request.headers.get("host", ""))
    if slug == DEFAULT_TENANT:
        # The default workspace is provisioned on demand so a fresh install is
        # usable without running the CLI first. Client workspaces are not:
        # an unknown subdomain must 404, never silently create an empty space.
        tenants.create(slug, os.environ.get("DEFAULT_TENANT_NAME", "Factures fournisseurs"))
    return slug if tenants.exists(slug) else None


def current_user(request: Request, slug: str) -> Optional[str]:
    session = request.session
    # The session must belong to the tenant being addressed, so a cookie can
    # never be replayed against another client's workspace.
    if session.get("tenant") != slug:
        return None
    email = session.get("email")
    # And the account must still exist: a cookie stays valid for 12 h, which
    # would otherwise outlive a user whose access has just been removed.
    if not email or db.get_user(slug, email) is None:
        return None
    return email


def _filters_from(request: Request) -> Dict[str, Any]:
    params = request.query_params
    return {
        "supplier": params.get("supplier", ""),
        "date_from": params.get("date_from", ""),
        "date_to": params.get("date_to", ""),
        "search": params.get("search", ""),
        "status": params.get("status", ""),
        "batch": params.get("batch", ""),
    }


def _page_context(request: Request, slug: str, email: str, active: str) -> Dict[str, Any]:
    # Close out imports orphaned by a restart first, so their summary is
    # offered like any other finished import.
    _running_batches(slug)
    return {
        "request": request,
        "tenant": slug,
        "tenant_name": tenants.display_name(slug),
        "user_email": email,
        "active_tab": active,
        "filters": _filters_from(request),
        "suppliers": db.distinct_suppliers(slug),
        "pending_corrections": db.count_pending_corrections(slug),
        "importing": pipeline.is_importing(slug),
        "pending_summary": db.pending_summary_batch(slug, email),
    }


# --------------------------------------------------------------------------- routes


@app.get("/healthz")
def healthz() -> Dict[str, Any]:
    return {"status": "ok", "api_key_configured": bool(os.environ.get("ANTHROPIC_API_KEY"))}


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> Response:
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/setup", response_class=HTMLResponse)
def setup_form(request: Request) -> Response:
    slug = current_tenant(request)
    if slug is None:
        return _unknown_tenant(request)
    if db.count_users(slug) > 0:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        "setup.html",
        {"request": request, "tenant": slug, "tenant_name": tenants.display_name(slug), "error": None},
    )


@app.post("/setup", response_class=HTMLResponse)
def setup_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
) -> Response:
    slug = current_tenant(request)
    if slug is None:
        return _unknown_tenant(request)
    if db.count_users(slug) > 0:
        return RedirectResponse("/login", status_code=303)

    problem = auth.password_problem(password)
    if problem:
        return templates.TemplateResponse(
            "setup.html",
            {
                "request": request,
                "tenant": slug,
                "tenant_name": tenants.display_name(slug),
                "error": problem,
            },
            status_code=400,
        )

    db.create_user(slug, email, auth.hash_password(password))
    request.session.update({"tenant": slug, "email": email.strip()})
    return RedirectResponse("/dashboard", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> Response:
    slug = current_tenant(request)
    if slug is None:
        return _unknown_tenant(request)
    if db.count_users(slug) == 0:
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "tenant": slug, "tenant_name": tenants.display_name(slug), "error": None},
    )


@app.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
) -> Response:
    slug = current_tenant(request)
    if slug is None:
        return _unknown_tenant(request)

    throttle_key = "{}|{}|{}".format(slug, (email or "").strip().lower(), _client_ip(request))
    waiting = auth.locked_seconds(throttle_key)
    if waiting:
        return _login_error(
            request,
            slug,
            "Trop de tentatives. Reessaie dans {} minute(s).".format(max(1, waiting // 60)),
            status_code=429,
        )

    identity = auth.authenticate(slug, email, password)
    if identity is None:
        auth.record_failure(throttle_key)
        logger.info("[%s] echec de connexion depuis %s", slug, _client_ip(request))
        return _login_error(request, slug, "Identifiants incorrects.", status_code=401)

    auth.clear_failures(throttle_key)
    # A fresh session id on privilege change, so a cookie fixed by an attacker
    # before login cannot be reused afterwards.
    request.session.clear()
    request.session.update({"tenant": slug, "email": identity})
    return RedirectResponse("/dashboard", status_code=303)


def _client_ip(request: Request) -> str:
    # X-Forwarded-For is only trustworthy behind a proxy that sets it; uvicorn
    # must run with --proxy-headers for request.client to already be the real one.
    return request.client.host if request.client else "?"


def _login_error(request: Request, slug: str, message: str, status_code: int) -> Response:
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "tenant": slug,
            "tenant_name": tenants.display_name(slug),
            "error": message,
        },
        status_code=status_code,
    )


@app.post("/logout")
def logout(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


def _unknown_tenant(request: Request) -> Response:
    return templates.TemplateResponse(
        "unknown_tenant.html",
        {"request": request, "host": request.headers.get("host", "")},
        status_code=404,
    )


def _require_login(request: Request):
    """Return (slug, email) or a redirect/error response to return as-is."""
    slug = current_tenant(request)
    if slug is None:
        return None, None, _unknown_tenant(request)
    if db.count_users(slug) == 0:
        return None, None, RedirectResponse("/setup", status_code=303)
    email = current_user(request, slug)
    if email is None:
        return None, None, RedirectResponse("/login", status_code=303)
    return slug, email, None


def _today() -> date:
    """The server's date; isolated so tests can pin it."""
    return date.today()


def _home_context(slug: str, today: date) -> Dict[str, Any]:
    """Everything the home page shows. No filters: it is always the whole workspace."""
    # Big figure: the last complete month, in its main currency. Other currencies
    # are listed beside it, never added to it.
    year, month = homepage.last_complete_month(today)
    month_period = homepage.period(year, month)
    month_rows = db.totals_by_currency(slug, month_period, month_period)
    month_currency = homepage.main_currency(month_rows)
    main_row = next((r for r in month_rows if r["currency"] == month_currency), None)
    headline = {
        "month_label": homepage.month_name(year, month),
        "empty": main_row is None,
        "amount_text": charts.format_amount(main_row["amount"]) if main_row else "",
        "currency": month_currency or "",
        "others": [
            {"amount_text": charts.format_amount(r["amount"]), "currency": r["currency"] or "devise inconnue"}
            for r in sorted(month_rows, key=lambda r: -float(r["amount"]))
            if r is not main_row
        ],
        "invoice_count": sum(int(r["invoice_count"]) for r in month_rows),
    }

    # Evolution: up to 12 months ending with the current one, in the main
    # currency of that window. Leading empty months are dropped; the current
    # month always keeps its place.
    window = homepage.month_window(today)
    window_rows = db.totals_by_currency(slug, window[0], window[-1])
    series_currency = homepage.main_currency(window_rows)
    series: List[Dict[str, Any]] = []
    if series_currency is not None:
        series = db.monthly_series(slug, window, series_currency)
        while len(series) > 1 and series[0]["invoice_count"] == 0:
            series.pop(0)
    other_currencies = sorted(
        {r["currency"] for r in window_rows if r["currency"] and r["currency"] != series_currency}
    )

    batch = db.latest_batch(slug)
    last_batch = None
    if batch is not None:
        batch = _reconcile_batch(slug, batch)
        last_batch = db.batch_summary(slug, batch["id"])
        if batch["status"] == "running":
            last_batch["done"] = batch["done"]
            last_batch["progress"] = pipeline.batch_progress(batch["id"], batch)

    # The heatmap follows the series currency; with nothing in the window it
    # falls back to the workspace's main currency, never to "all of them".
    heatmap_currency = series_currency
    if heatmap_currency is None:
        heatmap_currency = homepage.main_currency(db.totals_by_currency(slug, "0000-01", "9999-12"))

    alerts = homepage.top_price_alerts(
        products.summarise(db.product_lines(slug, {}), products.DEFAULT_ALERT_THRESHOLD)
    )

    return {
        "headline": headline,
        "uncertain_count": db.count_uncertain(slug),
        "series_currency": series_currency or "",
        "monthly": charts.monthly_columns(series, current_period=window[-1]),
        "monthly_other_currencies": other_currencies,
        "last_batch": last_batch,
        "alerts": alerts,
        "alert_threshold": products.DEFAULT_ALERT_THRESHOLD,
        "heatmap_currency": heatmap_currency or "",
        "heatmap": charts.daily_heatmap(db.heatmap_rows(slug, heatmap_currency)),
        "recent": db.latest_invoices(slug),
    }


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> Response:
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return redirect

    context = _page_context(request, slug, email, "dashboard")
    context.update(_home_context(slug, _today()))
    return templates.TemplateResponse("dashboard.html", context)


@app.get("/invoices", response_class=HTMLResponse)
def invoices(request: Request) -> Response:
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return redirect

    filters = _filters_from(request)
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page = 1
    per_page = 100

    sort = request.query_params.get("sort", "date_desc")
    if sort not in db.SORT_ORDERS:
        sort = "date_desc"
    rows, total = db.list_invoices(
        slug, filters, limit=per_page, offset=(page - 1) * per_page, sort=sort
    )
    # Every link on the page rebuilds its query from these, so a change of page,
    # status or sort never drops the other choices.
    kept = {key: value for key, value in filters.items() if value}
    if sort != "date_desc":
        kept["sort"] = sort

    context = _page_context(request, slug, email, "invoices")
    context.update(
        {
            "rows": [_row_to_view(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "page_count": max(1, (total + per_page - 1) // per_page),
            "sort": sort,
            "status_counts": db.status_counts(slug, filters),
            "page_query": urlencode(kept),
            "status_query": urlencode({k: v for k, v in kept.items() if k != "status"}),
            "editable_fields": list(db.EDITABLE_FIELDS),
            "rules": [dict(r) for r in db.list_rules(slug)],
            "batches": _running_batches(slug),
            "storage": _storage_view(slug),
        }
    )
    return templates.TemplateResponse("invoices.html", context)


@app.get("/products", response_class=HTMLResponse)
def products_page(request: Request) -> Response:
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return redirect

    filters = _filters_from(request)
    rows = db.product_lines(slug, filters)

    # Product search is applied here rather than in SQL: the free-text filter
    # shared with Invoices searches invoice provenance, not product wording.
    search = (request.query_params.get("product") or "").strip().lower()
    if search:
        rows = [r for r in rows
                if search in (r.get("label") or "").lower()
                or search in (r.get("product_key") or "").lower()]

    try:
        threshold = float(request.query_params.get("threshold", products.DEFAULT_ALERT_THRESHOLD))
    except ValueError:
        threshold = products.DEFAULT_ALERT_THRESHOLD
    threshold = min(200.0, max(0.0, threshold))

    summary = products.summarise(rows, threshold)
    options = products.product_options(summary)
    selection = products.parse_selection(request.query_params.get("selection", ""))
    if not selection["product_key"] and options:
        selection = products.parse_selection(options[0]["value"])

    history = products.history_points(rows, selection["product_key"], selection["supplier"])
    selected_rows = [
        item for item in summary
        if item["product_key"] == selection["product_key"]
        and (not selection["supplier"] or item["supplier"] == selection["supplier"])
    ]
    average = (sum(i["average"] for i in selected_rows) / len(selected_rows)) if selected_rows else None

    context = _page_context(request, slug, email, "products")
    context.update(
        {
            "rows": summary,
            "alert_count": sum(1 for item in summary if item["alert"]),
            "threshold": threshold,
            "product_search": request.query_params.get("product", ""),
            "options": options,
            "selection": selection,
            "selection_value": "{}|{}".format(selection["product_key"], selection["supplier"])
            if selection["supplier"] else selection["product_key"],
            "selected_label": selected_rows[0]["label"] if selected_rows else "",
            "history": charts.price_scatter(history, average),
            "invoices_with_lines": db.count_lines(slug),
        }
    )
    return templates.TemplateResponse("products.html", context)


def _reconcile_batch(slug: str, batch: Dict[str, Any]) -> Dict[str, Any]:
    """Close a batch the database says is running but no thread is processing.

    Background imports live in the server process: a restart mid-import leaves
    the batch 'running' forever, with a progress bar and a countdown that never
    move. Detected here and marked interrupted instead.
    """
    if batch["status"] == "running" and pipeline.batch_progress(batch["id"], batch) is None:
        db.finish_batch(slug, batch["id"], "interrupted")
        batch = dict(db.get_batch(slug, batch["id"]))
    return batch


def _running_batches(slug: str) -> List[Dict[str, Any]]:
    batches = [_reconcile_batch(slug, dict(b)) for b in db.active_batches(slug)]
    return [b for b in batches if b["status"] == "running"]


def _duration_seconds(batch: Dict[str, Any]) -> Optional[int]:
    try:
        started = datetime.fromisoformat(batch["started_at"])
        finished = datetime.fromisoformat(batch["finished_at"])
    except (TypeError, ValueError):
        return None
    return max(0, int((finished - started).total_seconds()))


def _storage_view(slug: str) -> Dict[str, Any]:
    usage = tenants.storage_usage(slug)
    quota = tenants.storage_quota_bytes(slug)
    percent = min(100.0, 100.0 * usage["total_bytes"] / quota) if quota else None
    return {
        "used": usage["total_bytes"],
        "files": usage["file_count"],
        "quota": quota,
        "percent": percent,
        # Warn before imports start failing on the quota, not after.
        "level": None if percent is None else ("critical" if percent >= 95 else "warn" if percent >= 80 else "ok"),
    }


def _row_to_view(row) -> Dict[str, Any]:
    data = dict(row)
    data["uncertain_fields"] = json.loads(data.get("uncertain_fields") or "[]")
    data["edited_fields"] = json.loads(data.get("edited_fields") or "[]")
    return data


# --------------------------------------------------------------------------- import


@app.post("/api/import")
async def api_import(request: Request, files: List[UploadFile] = File(...)) -> Response:
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return JSONResponse({"error": "Session expiree."}, status_code=401)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return JSONResponse(
            {"error": "ANTHROPIC_API_KEY n'est pas configuree sur le serveur."}, status_code=400
        )

    # The whole upload is held in memory while it is expanded, so its size is
    # capped: without this one request can exhaust the server for every client.
    limit = MAX_UPLOAD_MB * 1024 * 1024
    uploads = []
    total_bytes = 0
    for upload in files:
        content = await upload.read()
        total_bytes += len(content)
        if limit and total_bytes > limit:
            return JSONResponse(
                {"error": "Import trop volumineux (maximum {} Mo par envoi). "
                          "Depose les archives une par une.".format(MAX_UPLOAD_MB)},
                status_code=413,
            )
        uploads.append((upload.filename or "sans_nom", content, upload.content_type))

    outcome = pipeline.start_import(get_client(), slug, uploads, started_by=email)
    if "error" in outcome:
        return JSONResponse(outcome, status_code=409)
    return JSONResponse(outcome)


@app.get("/api/batches/{batch_id}")
def api_batch(request: Request, batch_id: str) -> Response:
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return JSONResponse({"error": "Session expiree."}, status_code=401)

    row = db.get_batch(slug, batch_id)
    if row is None:
        return JSONResponse({"error": "Lot introuvable."}, status_code=404)

    batch = _reconcile_batch(slug, dict(row))
    progress = pipeline.batch_progress(batch_id, batch) if batch["status"] == "running" else None
    if progress is not None:
        batch.update(progress)
    else:
        batch["elapsed_seconds"] = _duration_seconds(batch)
        batch["eta_seconds"] = 0
        batch["eta_basis"] = "termine"
    return JSONResponse(batch)


@app.get("/api/batches/{batch_id}/summary")
def api_batch_summary(request: Request, batch_id: str) -> Response:
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return JSONResponse({"error": "Session expiree."}, status_code=401)

    row = db.get_batch(slug, batch_id)
    if row is None:
        return JSONResponse({"error": "Lot introuvable."}, status_code=404)
    batch = _reconcile_batch(slug, dict(row))
    if batch["status"] == "running":
        return JSONResponse({"error": "Import encore en cours."}, status_code=409)

    summary = db.batch_summary(slug, batch_id)
    summary["elapsed_seconds"] = _duration_seconds(batch)
    return JSONResponse(summary)


@app.post("/api/batches/{batch_id}/ack")
def api_batch_ack(request: Request, batch_id: str) -> Response:
    """The user closed the import summary: don't offer it again."""
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return JSONResponse({"error": "Session expiree."}, status_code=401)
    db.acknowledge_batch(slug, batch_id)
    return JSONResponse({"status": "ok"})


# ------------------------------------------------------------------------- editing


def _coerce(field: str, raw: Any) -> Any:
    value = ("" if raw is None else str(raw)).strip()
    if value == "":
        return None
    if field in db.NUMERIC_FIELDS:
        cleaned = value.replace(" ", "").replace(" ", "").replace(",", ".")
        cleaned = "".join(c for c in cleaned if c.isdigit() or c in ".-")
        try:
            return float(cleaned)
        except ValueError:
            raise ValueError("Montant invalide : {!r}".format(raw))
    return value


@app.get("/api/invoices/{invoice_id}")
def api_get_invoice(request: Request, invoice_id: str) -> Response:
    """One invoice's extracted fields, for the review panel beside the document."""
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return JSONResponse({"error": "Session expiree."}, status_code=401)

    invoice = db.get_invoice(slug, invoice_id)
    if invoice is None:
        return JSONResponse({"error": "Facture introuvable."}, status_code=404)

    payload = {field: invoice[field] for field in db.EDITABLE_FIELDS}
    payload.update(
        {
            "id": invoice["id"],
            "filename": invoice["filename"],
            "archive": invoice["archive"],
            "has_file": bool(invoice["stored_name"]),
            "error": invoice["error"],
            "extraction_notes": invoice["extraction_notes"],
            "uncertain_fields": json.loads(invoice["uncertain_fields"] or "[]"),
            "uncertain_regions": json.loads(invoice["uncertain_regions"] or "[]"),
            "edited_fields": json.loads(invoice["edited_fields"] or "[]"),
        }
    )
    path = _stored_path(slug, invoice)
    payload["page_count"] = documents.page_count(path) if path else 0
    payload["document_kind"] = None
    if path and payload["page_count"]:
        payload["document_kind"] = "pdf" if path.suffix.lower() == ".pdf" else "image"
    return JSONResponse(payload)


@app.patch("/api/invoices/{invoice_id}")
async def api_edit_invoice(request: Request, invoice_id: str) -> Response:
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return JSONResponse({"error": "Session expiree."}, status_code=401)

    payload = await request.json()
    field = payload.get("field")
    if field not in db.EDITABLE_FIELDS:
        return JSONResponse({"error": "Champ non modifiable."}, status_code=400)

    invoice = db.get_invoice(slug, invoice_id)
    if invoice is None:
        return JSONResponse({"error": "Facture introuvable."}, status_code=404)

    try:
        value = _coerce(field, payload.get("value"))
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    previous = invoice[field]
    if (previous or None) == (value or None):
        return JSONResponse({"status": "unchanged"})

    db.update_invoice_field(slug, invoice_id, field, value)
    db.record_correction(
        slug,
        invoice_id,
        invoice["supplier_name"],
        field,
        previous,
        value,
        email,
    )
    logger.info("[%s] correction par %s : %s de la facture %s", slug, email, field, invoice_id)

    pending, learned = _after_review(slug)
    return JSONResponse(
        {"status": "ok", "value": value, "pending_corrections": pending, "learned": learned}
    )


def _after_review(slug: str) -> Tuple[int, Optional[Dict[str, Any]]]:
    """Pending corrections/confirmations, and the learning run they may trigger."""
    learned = None
    if db.count_pending_corrections(slug) >= AUTO_LEARN_THRESHOLD:
        # Enough signal accumulated: distill it into rules now, so the very
        # next import already benefits from them.
        learned = learning.refresh_rules(get_client(), slug)
    return db.count_pending_corrections(slug), learned


def _review_response(slug: str, invoice_id: str, fields: List[str], email: str) -> Response:
    try:
        state = db.confirm_fields(slug, invoice_id, fields, email)
    except LookupError:
        return JSONResponse({"error": "Facture introuvable."}, status_code=404)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    pending, learned = _after_review(slug)
    state.update({"status": "ok", "pending_corrections": pending, "learned": learned})
    return JSONResponse(state)


@app.post("/api/invoices/{invoice_id}/confirm")
async def api_confirm_field(request: Request, invoice_id: str) -> Response:
    """The doubtful value is right as extracted: drop the doubt, remember it."""
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return JSONResponse({"error": "Session expiree."}, status_code=401)
    payload = await request.json()
    field = payload.get("field") if isinstance(payload, dict) else None
    if not isinstance(field, str):
        return JSONResponse({"error": "Champ manquant."}, status_code=400)
    return _review_response(slug, invoice_id, [field], email)


@app.post("/api/invoices/{invoice_id}/validate")
def api_validate_invoice(request: Request, invoice_id: str) -> Response:
    """Every remaining doubtful value of the invoice is confirmed."""
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return JSONResponse({"error": "Session expiree."}, status_code=401)
    invoice = db.get_invoice(slug, invoice_id)
    if invoice is None:
        return JSONResponse({"error": "Facture introuvable."}, status_code=404)
    if invoice["error"]:
        return JSONResponse({"error": "Une facture en erreur ne peut pas etre validee."}, status_code=400)
    return _review_response(slug, invoice_id, json.loads(invoice["uncertain_fields"] or "[]"), email)


@app.post("/api/learn")
def api_learn(request: Request) -> Response:
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return JSONResponse({"error": "Session expiree."}, status_code=401)

    summary = learning.refresh_rules(get_client(), slug)
    summary["rules"] = [dict(r) for r in db.list_rules(slug)]
    return JSONResponse(summary)


@app.delete("/api/rules/{rule_id}")
def api_delete_rule(request: Request, rule_id: int) -> Response:
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return JSONResponse({"error": "Session expiree."}, status_code=401)
    db.delete_rule(slug, rule_id)
    return JSONResponse({"status": "ok"})


# ------------------------------------------------------------------ original files


# Extensions shown inline in the viewer, with the type they are served as.
VIEWABLE_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _stored_path(slug: str, invoice) -> Optional[Path]:
    """The invoice's stored original, or None if it has none or it is gone.

    Resolved inside the tenant's own directory with containment verified, so a
    crafted stored_name can never reach another tenant's files.
    """
    if not invoice["stored_name"]:
        return None
    directory = tenants.files_dir(slug).resolve()
    path = (directory / invoice["stored_name"]).resolve()
    if directory not in path.parents or not path.is_file():
        return None
    return path


@app.get("/invoices/{invoice_id}/pages/{page}.png")
def invoice_page(request: Request, invoice_id: str, page: int) -> Response:
    """One page of the original as an image, for the viewer to draw boxes on."""
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return redirect
    invoice = db.get_invoice(slug, invoice_id)
    path = _stored_path(slug, invoice) if invoice is not None else None
    media_type = VIEWABLE_TYPES.get(path.suffix.lower()) if path else None
    if path is None or media_type is None or not 1 <= page <= documents.page_count(path):
        return JSONResponse({"error": "Page indisponible."}, status_code=404)
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store, private"}
    if media_type != "application/pdf":
        return FileResponse(str(path), media_type=media_type, headers=headers)
    return Response(content=documents.render_page_png(path, page), media_type="image/png", headers=headers)


@app.get("/invoices/{invoice_id}/file")
def invoice_file(request: Request, invoice_id: str) -> Response:
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return redirect

    invoice = db.get_invoice(slug, invoice_id)
    path = _stored_path(slug, invoice) if invoice is not None else None
    if path is None:
        return JSONResponse({"error": "Document original indisponible."}, status_code=404)

    # The stored content type comes from the upload, so it is user-controlled:
    # serving an HTML or SVG "invoice" inline would run its script on this
    # origin. Only the formats the extractor accepts are shown inline; anything
    # else is handed over as a download of unknown type.
    media_type = VIEWABLE_TYPES.get(path.suffix.lower())
    disposition = "inline" if media_type else "attachment"
    return FileResponse(
        str(path),
        media_type=media_type or "application/octet-stream",
        headers={
            "Content-Disposition": '{}; filename="{}"'.format(disposition, path.name),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store, private",
        },
    )


# ---------------------------------------------------------------------- Excel export


@app.get("/invoices/export.xlsx")
def export_invoices(request: Request) -> Response:
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return redirect

    filters = _filters_from(request)
    rows, _ = db.list_invoices(
        slug, filters, limit=100000, offset=0, sort=request.query_params.get("sort", "date_desc")
    )
    workbook = build_workbook(rows)
    filename = "factures_{}_{:%Y%m%d_%H%M%S}.xlsx".format(slug, datetime.now())

    return Response(
        content=workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="{}"'.format(filename)},
    )


if __name__ == "__main__":
    import uvicorn

    # reload=False: auto-reload would watch the whole project directory,
    # including .venv (tens of thousands of files), which is slow/unreliable
    # to index on Windows and was causing the server to hang on startup.
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
