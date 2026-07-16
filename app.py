"""Local web app: drag & drop invoices, extract data via Claude, download Excel."""
from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional

from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

from excel_export import build_workbook
from extraction import process_upload

load_dotenv()

app = FastAPI(title="Extraction de factures")

_client: Optional[Anthropic] = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        # max_retries=6: the SDK retries 429/5xx (including 529 "overloaded")
        # with exponential backoff. The default of 2 attempts was not enough
        # to ride out API load spikes, leaving invoices unprocessed.
        _client = Anthropic(max_retries=6)  # reads ANTHROPIC_API_KEY from the environment
    return _client


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    with open(os.path.join("templates", "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "api_key_configured": bool(os.environ.get("ANTHROPIC_API_KEY"))}


@app.post("/process")
async def process(files: List[UploadFile] = File(...)) -> Response:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return JSONResponse(
            status_code=400,
            content={"error": "ANTHROPIC_API_KEY n'est pas configuree sur le serveur."},
        )

    client = get_client()
    results = []
    for upload in files:
        content = await upload.read()
        result = process_upload(client, upload.filename or "sans_nom", content, upload.content_type)
        results.append(result)

    workbook_bytes = build_workbook(results)
    filename = f"factures_{datetime.now():%Y%m%d_%H%M%S}.xlsx"

    return Response(
        content=workbook_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":
    import uvicorn

    # reload=False: auto-reload would watch the whole project directory,
    # including .venv (tens of thousands of files), which is slow/unreliable
    # to index on Windows and was causing the server to hang on startup.
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
