"""Multi-tenant invoice extraction platform.

Each client company is served on its own subdomain and gets its own database
and file storage (see tenants.py). Two working tabs: Dashboard (aggregates)
and Invoices (the reviewable, editable, exportable table).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

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
import db
import learning
import pipeline
import tenants
from config import (
    AUTO_LEARN_THRESHOLD,
    BASE_DIR,
    DEFAULT_TENANT,
    SESSION_COOKIE,
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
    same_site="lax",
    https_only=False,  # set True behind HTTPS in production
)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["amount"] = charts.format_amount
templates.env.filters["compact"] = charts.format_compact

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
    return session.get("email")


def _filters_from(request: Request) -> Dict[str, Any]:
    params = request.query_params
    return {
        "supplier": params.get("supplier", ""),
        "date_from": params.get("date_from", ""),
        "date_to": params.get("date_to", ""),
        "search": params.get("search", ""),
        "status": params.get("status", ""),
    }


def _page_context(request: Request, slug: str, email: str, active: str) -> Dict[str, Any]:
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

    identity = auth.authenticate(slug, email, password)
    if identity is None:
        logger.info("[%s] echec de connexion pour %r", slug, email)
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "tenant": slug,
                "tenant_name": tenants.display_name(slug),
                "error": "Identifiants incorrects.",
            },
            status_code=401,
        )

    request.session.update({"tenant": slug, "email": identity})
    return RedirectResponse("/dashboard", status_code=303)


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


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> Response:
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return redirect

    filters = _filters_from(request)
    stats = db.dashboard_stats(slug, filters)

    # Amounts are summed as stored; when several currencies are mixed the
    # template warns instead of silently presenting a meaningless total.
    currencies = stats["currencies"]
    currency_label = currencies[0]["currency"] if currencies else ""

    context = _page_context(request, slug, email, "dashboard")
    context.update(
        {
            "stats": stats,
            "currency_label": currency_label,
            "monthly": charts.monthly_columns(stats["by_month"]),
            "suppliers_chart": charts.supplier_bars(stats["by_supplier"]),
        }
    )
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

    rows, total = db.list_invoices(slug, filters, limit=per_page, offset=(page - 1) * per_page)

    context = _page_context(request, slug, email, "invoices")
    context.update(
        {
            "rows": [_row_to_view(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
            "page_count": max(1, (total + per_page - 1) // per_page),
            "editable_fields": list(db.EDITABLE_FIELDS),
            "rules": [dict(r) for r in db.list_rules(slug)],
            "batches": [dict(b) for b in db.active_batches(slug)],
        }
    )
    return templates.TemplateResponse("invoices.html", context)


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

    uploads = []
    for upload in files:
        uploads.append((upload.filename or "sans_nom", await upload.read(), upload.content_type))

    outcome = pipeline.start_import(get_client(), slug, uploads)
    if "error" in outcome:
        return JSONResponse(outcome, status_code=409)
    return JSONResponse(outcome)


@app.get("/api/batches/{batch_id}")
def api_batch(request: Request, batch_id: str) -> Response:
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return JSONResponse({"error": "Session expiree."}, status_code=401)

    batch = db.get_batch(slug, batch_id)
    if batch is None:
        return JSONResponse({"error": "Lot introuvable."}, status_code=404)
    return JSONResponse(dict(batch))


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

    pending = db.count_pending_corrections(slug)
    learned = None
    if pending >= AUTO_LEARN_THRESHOLD:
        # Enough signal accumulated: distill the corrections into rules now, so
        # the very next import already benefits from them.
        learned = learning.refresh_rules(get_client(), slug)

    return JSONResponse(
        {
            "status": "ok",
            "value": value,
            "pending_corrections": db.count_pending_corrections(slug),
            "learned": learned,
        }
    )


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


@app.get("/invoices/{invoice_id}/file")
def invoice_file(request: Request, invoice_id: str) -> Response:
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return redirect

    invoice = db.get_invoice(slug, invoice_id)
    if invoice is None or not invoice["stored_name"]:
        return JSONResponse({"error": "Document original indisponible."}, status_code=404)

    # Resolve inside the tenant's own directory and verify containment, so a
    # crafted stored_name can never reach another tenant's files.
    directory = tenants.files_dir(slug).resolve()
    path = (directory / invoice["stored_name"]).resolve()
    if directory not in path.parents or not path.exists():
        return JSONResponse({"error": "Document original indisponible."}, status_code=404)

    return FileResponse(
        str(path),
        media_type=invoice["content_type"] or "application/octet-stream",
        headers={"Content-Disposition": 'inline; filename="{}"'.format(path.name)},
    )


# ---------------------------------------------------------------------- Excel export


@app.get("/invoices/export.xlsx")
def export_invoices(request: Request) -> Response:
    slug, email, redirect = _require_login(request)
    if redirect is not None:
        return redirect

    filters = _filters_from(request)
    rows, _ = db.list_invoices(slug, filters, limit=100000, offset=0)
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
