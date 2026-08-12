"""Local web app: drag & drop invoices, extract data via Claude, download Excel."""
from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Optional

from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response

from excel_export import build_workbook
from extraction import InvoiceResult, InvoiceSource, expand_upload, process_source

load_dotenv()

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="Extraction de factures")

# An archive can hold hundreds of invoices; processed one at a time they would
# take hours, since each is a separate API round-trip. Requests are sent
# concurrently instead, kept modest so the API rate limits are not hit.
MAX_CONCURRENT_EXTRACTIONS = 8

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


def _process_all(client: Anthropic, sources: List[InvoiceSource]) -> List[InvoiceResult]:
    """Extract every invoice concurrently, preserving the input order."""
    results: List[Optional[InvoiceResult]] = [None] * len(sources)
    done = 0

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_EXTRACTIONS) as pool:
        pending = {
            pool.submit(process_source, client, source): index
            for index, source in enumerate(sources)
        }
        for future in as_completed(pending):
            index = pending[future]
            results[index] = future.result()
            done += 1
            if done % 10 == 0 or done == len(sources):
                logger.info("Factures traitees : %d/%d", done, len(sources))

    return [r for r in results if r is not None]


@app.post("/process")
async def process(files: List[UploadFile] = File(...)) -> Response:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return JSONResponse(
            status_code=400,
            content={"error": "ANTHROPIC_API_KEY n'est pas configuree sur le serveur."},
        )

    sources: List[InvoiceSource] = []
    for upload in files:
        content = await upload.read()
        sources.extend(expand_upload(upload.filename or "sans_nom", content, upload.content_type))

    logger.info("%d fichier(s) deposes -> %d facture(s) a traiter", len(files), len(sources))

    client = get_client()
    # Run off the event loop: the extraction is blocking (HTTP + PDF rendering)
    # and would otherwise freeze the server for the whole batch.
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(None, _process_all, client, sources)

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
