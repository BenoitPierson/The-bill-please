# Refonte Brume, livraison 2 (page Factures) — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** transformer la page Factures en vue liste / détail avec visionneuse navigable, cadres sur les champs douteux, confirmation et validation qui alimentent les règles, tri et filtres, et journal d'import en base sans aucun affichage des doublons.

**Architecture :** les données d'abord (migrations, journal d'import, cadres, confirmations, tri, rendu des pages), chacune testée par pytest ; puis le gabarit et le JavaScript de la page (liste, détail, visionneuse), vérifiés par un script Playwright hors dépôt. Le rendu des pages vit dans un petit module `documents.py`, testable sans serveur.

**Tech Stack :** Python 3.8 (Anaconda), FastAPI, Jinja2, SQLite, PyMuPDF, JavaScript sans dépendance, pytest.

**Spec :** `docs/superpowers/specs/2026-10-26-refonte-brume-factures-design.md`

## Global Constraints

- Compatibilité Python 3.8 : `from __future__ import annotations` en tête de module ; `typing.List` / `typing.Optional` dans les signatures de routes de `app.py`.
- Aucun texte issu d'une facture inséré via `innerHTML` : nœuds et `textContent`.
- Aucun script inline ; ressources via `static_url('…')` ; un seul fichier `static/app.js` et un seul `static/app.css` (convention du projet).
- Aucune bibliothèque JavaScript externe ; politique de sécurité inchangée.
- Migrations additives uniquement (`MIGRATIONS`) ; aucune table supprimée.
- Champs modifiables et confirmables : `db.EDITABLE_FIELDS` uniquement.
- Codes du journal : `DUPLICATE`, `UNSUPPORTED`, `EXTRACTION`, `QUOTA`, `OTHER`.
- Tri : `date_desc` (défaut), `date_asc`, `amount_desc`, `amount_asc`.
- Rendu des pages PDF : 200 dpi. Zoom de la visionneuse : 50 % à 400 %.
- Aucun texte d'interface ne nomme le modèle : « l'automate ».
- Mouvement : seules `transform` et `opacity` animées ; `prefers-reduced-motion: reduce` → instantané ; survols sous `@media (hover: hover) and (pointer: fine)` ; aucune animation sur une action clavier.
- Chaque commit se termine par :
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` et
  `Claude-Session: https://claude.ai/code/session_01GHDHZs4Bn8jD7j6FrpG3DC`.

## Review Focus

- Un fichier conservé puis supprimé du disque (`stored_name` présent, fichier absent) : la route des pages répond 404 et la visionneuse affiche son message, sans erreur 500 — test dans la tâche 4.
- Un champ confirmé puis corrigé : la correction est enregistrée normalement et le champ passe en « corrigé » — test dans la tâche 3.
- Deux copies du même document dans une même archive : la seconde est journalisée `DUPLICATE` avec la facture d'origine — test dans la tâche 1.
- La pagination conserve tri et filtres — test dans la tâche 5.
- `?id=` qui ne correspond à aucune ligne affichée : la première ligne est sélectionnée — vérification Playwright dans la tâche 5.

---

## Structure des fichiers

| Fichier | Rôle |
| --- | --- |
| `db.py` | Migrations, journal d'import, confirmations, tri, comptes par état |
| `extraction.py` | Cadres dans le schéma et le prompt, `clean_regions` |
| `pipeline.py` | Écriture du journal et des cadres |
| `learning.py` | Format des confirmations |
| `documents.py` (nouveau) | Nombre de pages et rendu PNG d'une page |
| `app.py` | Routes `confirm`, `validate`, `pages/{n}.png`, page Factures |
| `templates/invoices.html`, `static/app.js`, `static/app.css` | Page liste / détail, visionneuse |
| `CLAUDE.md` | Documentation |

---

### Task 1 : migrations et journal d'import

**Files :**
- Modify : `db.py` (`SCHEMA`, `MIGRATIONS`, `connect`, `_migrate`, `batch_summary`, `duplicate_summary` ; suppression de `record_duplicate` et `list_duplicates`), `pipeline.py` (`_record_failure`, `_process_one`), `app.py` (route `invoices` : plus de `duplicates` / `duplicate_summary` dans le contexte)
- Test : `tests/test_migrations.py`, `tests/test_import_log.py`

**Interfaces :**
- Produces :
  - colonnes `invoices.uncertain_regions TEXT NOT NULL DEFAULT '[]'`, `corrections.kind TEXT NOT NULL DEFAULT 'correction'` (déclarées dans `SCHEMA` **et** `MIGRATIONS`) ;
  - table `import_log(id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT, archive TEXT, filename TEXT NOT NULL, reason TEXT NOT NULL, message TEXT, duplicate_of TEXT, invoice_id TEXT, file_size INTEGER, created_at TEXT NOT NULL)` et index `idx_import_log_batch` ;
  - `IMPORT_REASONS = ("DUPLICATE", "UNSUPPORTED", "EXTRACTION", "QUOTA", "OTHER")` ;
  - `reason_for_error(message: Optional[str]) -> str` — `error_kind` → code (`quota`→`QUOTA`, `unsupported`→`UNSUPPORTED`, `extraction`→`EXTRACTION`, autre→`OTHER`) ;
  - `log_import_event(slug, batch_id, filename, archive, reason, message, file_size=None, duplicate_of=None, invoice_id=None) -> None` ;
  - `duplicate_summary(slug) -> Dict[str, int]` (mêmes clés `count`, `bytes`) et `batch_summary` (mêmes clés qu'aujourd'hui) calculés depuis `import_log`.

- [ ] **Step 1 : tests qui échouent**

`tests/test_migrations.py` : un helper crée `data.db` avec l'ancien `SCHEMA` de `origin/main` (copié dans le test, sans les nouvelles colonnes ni `import_log`), y insère deux lignes `duplicates`, vide `db._initialised`, puis ouvre `db.connect`.

```python
def test_old_database_gets_new_columns_and_log(old_tenant):
    with db.connect(old_tenant) as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(invoices)")}
        assert "uncertain_regions" in cols
        assert "kind" in {r["name"] for r in conn.execute("PRAGMA table_info(corrections)")}
        rows = conn.execute("SELECT reason FROM import_log").fetchall()
    assert [r["reason"] for r in rows] == ["DUPLICATE", "DUPLICATE"]

def test_duplicates_are_copied_only_once(old_tenant):
    with db.connect(old_tenant):
        pass
    db._initialised.clear()
    with db.connect(old_tenant) as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM import_log").fetchone()["n"] == 2
```

`tests/test_import_log.py` (pipeline appelé avec `pipeline.process_upload` remplacé par un faux qui renvoie un `InvoiceResult` sans erreur) :

```python
def test_reason_for_error():
    assert db.reason_for_error("Quota de stockage atteint : …") == "QUOTA"
    assert db.reason_for_error("Format non pris en charge (ni PDF, ni image).") == "UNSUPPORTED"
    assert db.reason_for_error("Erreur API : surcharge") == "EXTRACTION"
    assert db.reason_for_error("autre chose") == "OTHER"

def test_duplicate_in_same_archive_is_logged(tenant, fake_extraction):
    batch = db.create_batch(tenant, "a.zip", 2)
    state = pipeline._BatchState(tenant)
    same = b"%PDF-1.4 same bytes"
    first = InvoiceSource(filename="m/x.pdf", archive="a.zip", data=same)
    second = InvoiceSource(filename="n/x.pdf", archive="a.zip", data=same)
    assert pipeline._process_one(None, tenant, batch, first, [], state) == pipeline.OK
    assert pipeline._process_one(None, tenant, batch, second, [], state) == pipeline.DUPLICATE
    (row,) = rows_of(tenant, "import_log")
    assert row["reason"] == "DUPLICATE" and row["filename"] == "n/x.pdf" and row["duplicate_of"]

def test_unsupported_file_is_logged_and_kept_as_error_row(tenant):
    batch = db.create_batch(tenant, "a.zip", 1)
    source = InvoiceSource(filename="notes.txt", archive="a.zip",
                           skip_reason="Format non pris en charge (ni PDF, ni image).")
    pipeline._process_one(None, tenant, batch, source, [], pipeline._BatchState(tenant))
    (log,) = rows_of(tenant, "import_log")
    assert log["reason"] == "UNSUPPORTED" and log["invoice_id"]
    assert db.get_invoice(tenant, log["invoice_id"])["error"].startswith("Format non pris en charge")

def test_batch_summary_counts_duplicates_from_log(tenant):
    batch = db.create_batch(tenant, "a.zip", 1)
    db.log_import_event(tenant, batch, "x.pdf", "a.zip", "DUPLICATE", "…", file_size=10, duplicate_of="abc")
    summary = db.batch_summary(tenant, batch)
    assert summary["duplicates"] == 1 and summary["duplicate_examples"][0]["filename"] == "x.pdf"
```

(`rows_of(slug, table)` : helper de test qui renvoie les lignes en dictionnaires. `fake_extraction` : fixture qui remplace `pipeline.process_upload`.)

- [ ] **Step 2 : vérifier l'échec** — `python -m pytest tests/test_migrations.py tests/test_import_log.py -q`.
- [ ] **Step 3 : implémenter** — dans `connect`, relever avant `executescript(SCHEMA)` si `import_log` existait ; `_migrate` reçoit ce booléen et, si la table vient d'être créée, recopie `duplicates` (`INSERT … SELECT batch_id, archive, filename, 'DUPLICATE', 'Document identique à une facture déjà importée.', duplicate_of, NULL, file_size, created_at`). Message d'un doublon : `"Document identique à une facture déjà importée."`. `_record_failure` et le cas `result.error` de `_process_one` écrivent aussi `log_import_event` avec `invoice_id`.
- [ ] **Step 4 : vérifier le succès** — `python -m pytest -q` → tout passe.
- [ ] **Step 5 : commit** — `git commit -m "Factures : journal d'import en base, colonnes de revue"`.

---

### Task 2 : cadres des champs douteux à l'extraction

**Files :**
- Modify : `extraction.py` (`INVOICE_SCHEMA`, `SYSTEM_PROMPT`, `InvoiceResult`, `extract_invoice`), `pipeline.py` (insertion), `db.py` (`insert_invoice` sérialise `uncertain_regions`)
- Test : `tests/test_regions.py`

**Interfaces :**
- Consumes : colonne `invoices.uncertain_regions` (tâche 1).
- Produces :
  - `clean_regions(raw: Any, uncertain_fields: Sequence[str], page_count: int) -> List[Dict[str, Any]]` — éléments `{"field": str, "page": int, "x": float, "y": float, "width": float, "height": float}`, valeurs arrondies à 4 décimales ;
  - `InvoiceResult.uncertain_regions: List[dict]` ;
  - `db.insert_invoice` accepte `record["uncertain_regions"]` (liste, sérialisée en JSON, `[]` par défaut).

- [ ] **Step 1 : tests qui échouent**

```python
def test_regions_keep_only_uncertain_fields():
    raw = [{"field": "invoice_number", "page": 1, "x": .1, "y": .2, "width": .3, "height": .05},
           {"field": "supplier_name", "page": 1, "x": .1, "y": .1, "width": .2, "height": .05}]
    assert [r["field"] for r in clean_regions(raw, ["invoice_number"], 1)] == ["invoice_number"]

def test_regions_drop_pages_out_of_range_and_empty_boxes():
    raw = [{"field": "invoice_date", "page": 3, "x": .1, "y": .1, "width": .1, "height": .1},
           {"field": "invoice_date", "page": 1, "x": .1, "y": .1, "width": 0, "height": .1}]
    assert clean_regions(raw, ["invoice_date"], 2) == []

def test_regions_are_clamped_to_the_page():
    raw = [{"field": "total_amount", "page": 1, "x": -.2, "y": .9, "width": .5, "height": .4}]
    (box,) = clean_regions(raw, ["total_amount"], 1)
    assert box["x"] == 0.0 and box["y"] == 0.9
    assert box["width"] == 0.5 and box["height"] == 0.1

def test_regions_ignore_garbage():
    assert clean_regions("nope", ["total_amount"], 1) == []
    assert clean_regions([{"field": "total_amount", "page": "a"}], ["total_amount"], 1) == []

def test_schema_requires_regions():
    assert "uncertain_regions" in INVOICE_SCHEMA["required"]

def test_insert_invoice_stores_regions(tenant):
    box = {"field": "total_amount", "page": 1, "x": .1, "y": .1, "width": .2, "height": .05}
    invoice_id = db.insert_invoice(tenant, {"filename": "f.pdf", "uncertain_regions": [box]})
    assert json.loads(db.get_invoice(tenant, invoice_id)["uncertain_regions"]) == [box]
```

- [ ] **Step 2 : vérifier l'échec** — `python -m pytest tests/test_regions.py -q`.
- [ ] **Step 3 : implémenter** — schéma : `uncertain_regions` = tableau d'objets `field` (enum `EXTRACTED_FIELDS`), `page` (integer), `x`, `y`, `width`, `height` (number), tous requis, `additionalProperties: false` ; ajouté à `required`. Puce ajoutée à la fin de `SYSTEM_PROMPT`, texte exact :

```
- Pour chaque champ de uncertain_fields, ajoute dans uncertain_regions la zone du document ou tu as lu la valeur : numero de page (1 pour la premiere image) et cadre en proportions de la page, de 0 a 1, origine en haut a gauche (x, y, width, height). Le cadre peut etre approximatif mais doit entourer la valeur. Laisse uncertain_regions vide si uncertain_fields est vide.
```

Bornage : `x, y` ramenés dans `[0, 1]`, puis `width ≤ 1 − x`, `height ≤ 1 − y` ; écarter si `width ≤ 0` ou `height ≤ 0`. `extract_invoice` appelle `clean_regions(data.get("uncertain_regions"), uncertain, len(pages))`.
- [ ] **Step 4 : vérifier le succès** — `python -m pytest -q`.
- [ ] **Step 5 : commit** — `git commit -m "Factures : cadres des champs douteux à l'extraction"`.

---

### Task 3 : confirmer, valider, apprentissage

**Files :**
- Modify : `db.py` (`record_correction`, `update_invoice_field`, nouvelle `confirm_fields`), `app.py` (deux routes, factorisation de l'auto-apprentissage), `learning.py` (`_format_corrections`, `RULE_SYSTEM_PROMPT`)
- Test : `tests/test_invoice_review.py`, `tests/test_learning.py`

**Interfaces :**
- Consumes : colonnes `corrections.kind`, `invoices.uncertain_regions` (tâche 1).
- Produces :
  - `record_correction(slug, invoice_id, supplier_name, field, old_value, new_value, user_email, kind="correction") -> None` ;
  - `confirm_fields(slug, invoice_id, fields: Sequence[str], user_email: str) -> Dict[str, Any]` — retourne `{"uncertain_fields": list, "uncertain_regions": list}` ; lève `ValueError` si un champ n'est pas dans `EDITABLE_FIELDS` ou pas douteux, `LookupError` si la facture n'existe pas ;
  - `update_invoice_field` retire aussi les cadres du champ corrigé ;
  - routes `POST /api/invoices/{invoice_id}/confirm` (`{"field": str}`) et `POST /api/invoices/{invoice_id}/validate` ; réponse `{"status": "ok", "uncertain_fields", "uncertain_regions", "pending_corrections", "learned"}` ;
  - `app._after_review(slug: str) -> Tuple[int, Optional[Dict]]` — compte des corrections en attente, et résultat de `learning.refresh_rules` si `AUTO_LEARN_THRESHOLD` est atteint ; utilisée aussi par le `PATCH` existant.

- [ ] **Step 1 : tests qui échouent** (client de test connecté comme dans `tests/test_home_route.py`)

```python
def test_confirm_removes_doubt_and_region_and_records_confirmation(client, tenant):
    box = {"field": "invoice_number", "page": 1, "x": .1, "y": .1, "width": .2, "height": .05}
    iid = add(tenant, invoice_number="A1", uncertain_fields=["invoice_number"], uncertain_regions=[box])
    body = client.post(f"/api/invoices/{iid}/confirm", json={"field": "invoice_number"}).json()
    assert body["uncertain_fields"] == [] and body["uncertain_regions"] == []
    (c,) = db.pending_corrections(tenant)
    assert c["kind"] == "confirmation" and c["old_value"] == c["new_value"] == "A1"
    assert "invoice_number" not in json.loads(db.get_invoice(tenant, iid)["edited_fields"])

def test_confirm_rejects_a_field_that_is_not_doubtful(client, tenant):
    iid = add(tenant, invoice_number="A1")
    assert client.post(f"/api/invoices/{iid}/confirm", json={"field": "invoice_number"}).status_code == 400
    assert client.post(f"/api/invoices/{iid}/confirm", json={"field": "filename"}).status_code == 400

def test_validate_confirms_every_doubtful_field(client, tenant):
    iid = add(tenant, uncertain_fields=["invoice_number", "invoice_date"])
    assert client.post(f"/api/invoices/{iid}/validate").json()["uncertain_fields"] == []
    assert len(db.pending_corrections(tenant)) == 2

def test_validate_refuses_an_invoice_in_error(client, tenant):
    iid = add(tenant, error="Erreur API : x", uncertain_fields=["invoice_number"])
    assert client.post(f"/api/invoices/{iid}/validate").status_code == 400

def test_confirmations_reach_the_learning_threshold(client, tenant, monkeypatch):
    calls = []
    monkeypatch.setattr(learning, "refresh_rules", lambda c, s: calls.append(s) or {"corrections": 3, "rules_updated": 1})
    iid = add(tenant, uncertain_fields=["invoice_number", "invoice_date", "currency"])
    client.post(f"/api/invoices/{iid}/validate")
    assert calls == [tenant]

def test_confirmed_then_corrected_field_is_marked_edited(client, tenant):
    iid = add(tenant, invoice_number="A1", uncertain_fields=["invoice_number"])
    client.post(f"/api/invoices/{iid}/confirm", json={"field": "invoice_number"})
    client.patch(f"/api/invoices/{iid}", json={"field": "invoice_number", "value": "A2"})
    assert json.loads(db.get_invoice(tenant, iid)["edited_fields"]) == ["invoice_number"]
    assert [c["kind"] for c in db.pending_corrections(tenant)] == ["confirmation", "correction"]
```

`tests/test_learning.py` :

```python
def test_confirmations_are_described_as_such():
    text = learning._format_corrections([
        {"field": "invoice_number", "old_value": "A1", "new_value": "A1", "kind": "confirmation"},
        {"field": "invoice_date", "old_value": "2026-01-02", "new_value": "2026-02-01", "kind": "correction"}])
    assert 'valeur "A1" signalée douteuse, confirmée exacte' in text
    assert 'extrait "2026-01-02" -> corrige en "2026-02-01"' in text
```

- [ ] **Step 2 : vérifier l'échec** — `python -m pytest tests/test_invoice_review.py tests/test_learning.py -q`.
- [ ] **Step 3 : implémenter** — ligne ajoutée aux principes de `RULE_SYSTEM_PROMPT`, texte exact : `- Une "confirmation" signifie que la valeur extraite etait juste alors que l'extraction en doutait : la consigne peut indiquer de ne plus douter de ce champ pour ce fournisseur.` Une confirmation ne touche pas `edited_fields`. `_format_corrections` lit `correction["kind"]` (ligne `sqlite3.Row` ou dict).
- [ ] **Step 4 : vérifier le succès** — `python -m pytest -q`.
- [ ] **Step 5 : commit** — `git commit -m "Factures : confirmer, valider et apprendre des confirmations"`.

---

### Task 4 : tri, comptes par état, détail enrichi et pages rendues

**Files :**
- Create : `documents.py`
- Modify : `db.py` (`list_invoices`, `status_counts`), `app.py` (`invoices`, `export_invoices`, `api_get_invoice`, nouvelle route des pages)
- Test : `tests/test_invoice_list.py`, `tests/test_pages_route.py`

**Interfaces :**
- Produces :
  - `db.SORT_ORDERS: Dict[str, str]` (valeurs de la spec) et `list_invoices(slug, filters, limit=500, offset=0, sort="date_desc")` ;
  - `db.status_counts(slug, filters) -> Dict[str, int]` — clés `all`, `uncertain`, `errors`, calculées avec les autres filtres mais en ignorant `filters["status"]` ;
  - `documents.page_count(path: Path) -> int` (PDF : nombre de pages ; JPG/PNG/WEBP : 1 ; autre ou illisible : 0) et `documents.render_page_png(path: Path, page: int, dpi: int = 200) -> bytes` ;
  - `GET /invoices/{invoice_id}/pages/{page}.png` ;
  - `GET /api/invoices/{invoice_id}` gagne `uncertain_regions` (liste), `page_count` (int), `document_kind` (`"pdf"`, `"image"` ou `None`) ;
  - contexte de la page Factures : `sort`, `status_counts`, plus de `duplicates` ni `duplicate_summary`.

- [ ] **Step 1 : tests qui échouent**

```python
@pytest.mark.parametrize("sort,expected", [
    ("date_desc", ["B", "A", "N"]), ("date_asc", ["A", "B", "N"]),
    ("amount_desc", ["A", "B", "N"]), ("amount_asc", ["B", "A", "N"]), ("drop table", ["B", "A", "N"])])
def test_sort_orders_put_missing_values_last(tenant, sort, expected):
    add(tenant, invoice_number="A", invoice_date="2026-01-01", total_amount=50.0)
    add(tenant, invoice_number="B", invoice_date="2026-02-01", total_amount=10.0)
    add(tenant, invoice_number="N")
    rows, _ = db.list_invoices(tenant, {}, sort=sort)
    assert [r["invoice_number"] for r in rows] == expected

def test_status_counts_ignore_the_status_filter(tenant):
    add(tenant); add(tenant, uncertain_fields=["invoice_number"]); add(tenant, error="Erreur API : x")
    assert db.status_counts(tenant, {"status": "errors"}) == {"all": 3, "uncertain": 1, "errors": 1}

def test_invoices_page_has_no_duplicates_panel_and_keeps_sort_in_pagination(client, tenant):
    for n in range(101):
        add(tenant, invoice_number="N{}".format(n))
    page = client.get("/invoices?sort=amount_asc&status=ok").text
    assert "doublons" not in page.lower()
    assert "sort=amount_asc" in page and "page=2" in page
```

`tests/test_pages_route.py` (un PDF de 2 pages créé avec PyMuPDF dans le dossier `files/` de l'espace, référencé par `stored_name`) :

```python
def test_pdf_page_is_rendered_as_png(client, pdf_invoice):
    response = client.get(f"/invoices/{pdf_invoice}/pages/2.png")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert "no-store" in response.headers["cache-control"]

def test_page_out_of_range_is_404(client, pdf_invoice):
    assert client.get(f"/invoices/{pdf_invoice}/pages/3.png").status_code == 404
    assert client.get(f"/invoices/{pdf_invoice}/pages/0.png").status_code == 404

def test_missing_file_on_disk_is_404(client, tenant, pdf_invoice):
    (tenants.files_dir(tenant) / db.get_invoice(tenant, pdf_invoice)["stored_name"]).unlink()
    assert client.get(f"/invoices/{pdf_invoice}/pages/1.png").status_code == 404

def test_api_detail_reports_pages_and_regions(client, pdf_invoice):
    data = client.get(f"/api/invoices/{pdf_invoice}").json()
    assert data["page_count"] == 2 and data["document_kind"] == "pdf" and data["uncertain_regions"] == []

def test_documents_page_count_of_an_image(tmp_path):
    path = tmp_path / "x.png"
    Image.new("RGB", (10, 10)).save(path)
    assert documents.page_count(path) == 1
```

- [ ] **Step 2 : vérifier l'échec** — `python -m pytest tests/test_invoice_list.py tests/test_pages_route.py -q`.
- [ ] **Step 3 : implémenter** — la route des pages reprend le contrôle de `invoice_file` (chemin résolu, appartenance, `VIEWABLE_TYPES`) ; pour une photo, la page 1 renvoie le fichier avec son type ; en-têtes `Cache-Control: no-store, private` et `X-Content-Type-Options: nosniff`. Une valeur de `sort` hors de `SORT_ORDERS` retombe sur `date_desc`. `export_invoices` transmet aussi `sort` à `list_invoices`. La pagination du gabarit actuel est réécrite pour reconstruire la requête à partir des paramètres (filtres, `status`, `sort`) plutôt que par remplacement de chaîne.
- [ ] **Step 4 : vérifier le succès** — `python -m pytest -q`.
- [ ] **Step 5 : commit** — `git commit -m "Factures : tri, comptes par état et pages rendues"`.

---

### Task 5 : page liste / détail

**Files :**
- Modify : `templates/invoices.html` (réécriture), `static/app.js` (sections `document modal`, `import summary`, nouvelles sections), `static/app.css`
- Test : `tests/test_invoice_list.py` (ajouts) ; vérification Playwright (script hors dépôt, dans le dossier de travail)

**Interfaces :**
- Consumes : tâches 3 et 4 (routes, contexte `sort`, `status_counts`).
- Produces (repères du gabarit utilisés par le JS et la tâche 6) :
  - `#invoiceList` : lignes `tr[data-id]` avec `data-state` (`ok`, `uncertain`, `edited`, `error`) ;
  - `#detailPane` (`data-empty` quand aucune facture), `#detailTitle`, `#detailMeta`, `#detailPrev`, `#detailNext`, `#detailOpen`, `#detailNotes`, `#detailError`, `#validateBtn` ;
  - champs `#detailFields input[data-field]`, chacun suivi de `button[data-confirm="<champ>"]` (masqué si le champ n'est pas douteux) ;
  - `#viewer` (rempli par la tâche 6) ;
  - `#rulesBtn` / `#rulesPanel` (panneau latéral, `hidden` par défaut) ;
  - `#importBtn` / `#importPanel` avec les identifiants actuels (`dropzone`, `fileInput`, `fileList`, `startImport`, `importStatus`, `progressWrap`, `progressBar`, `progressText`, `etaText`) pour que le JS d'import reste inchangé ;
  - barre d'outils : liens d'état qui gardent les autres paramètres, `form#filters` (`search`, `supplier`, `date_from`, `date_to`, `sort`, `status` caché) ; le `select[name=sort]` se soumet au changement ;
  - événement JS `invoice:selected` (détail `{id, data}`) émis sur `#detailPane`, écouté par la visionneuse.

- [ ] **Step 1 : tests qui échouent** (ajouts dans `tests/test_invoice_list.py`)

```python
def test_page_lists_rows_with_state_and_has_detail_pane(client, tenant):
    add(tenant, supplier_name="Bidco", uncertain_fields=["invoice_number"])
    add(tenant, filename="scan_0.pdf", error="Erreur API : x")
    page = client.get("/invoices").text
    assert 'data-state="uncertain"' in page and 'data-state="error"' in page
    assert 'id="detailPane"' in page and 'id="viewer"' in page and 'id="docModal"' not in page
    assert "scan_0.pdf" in page

def test_status_links_keep_other_filters(client, tenant):
    add(tenant, supplier_name="Bidco")
    page = client.get("/invoices?supplier=Bidco&sort=amount_desc").text
    assert "status=uncertain" in page and "supplier=Bidco" in page and "sort=amount_desc" in page
```

- [ ] **Step 2 : vérifier l'échec** — `python -m pytest tests/test_invoice_list.py -q`.
- [ ] **Step 3 : gabarit et CSS** — structure et textes de la section 1 de la spec ; grille `minmax(0, 1fr) minmax(0, 1.1fr)` ; sous 900 px, liste seule et détail en plein écran (`#detailPane.is-open`) avec bouton « Retour » ; panneau des règles en feuille latérale droite avec voile, refermé par Échap, le voile ou « Fermer » ; panneau d'import en feuille ancrée sous `#importBtn` ; déposer des fichiers n'importe où sur la page ouvre ce panneau avec les fichiers. Liste vide : « Aucune facture ne correspond à ces filtres. » et lien « Réinitialiser les filtres » (`/invoices`), sans détail affiché. En-tête : « N factures · M à vérifier · K en erreur », les deux derniers en liens vers l'état correspondant (`status_counts`). Ligne sélectionnée : `aria-selected="true"`, fond `--series-1-tint`. Pastilles d'état : neutre `--series-1-soft`, à vérifier `--uncertain-edge`, corrigée `--edited-edge`, erreur `--apricot`.
- [ ] **Step 4 : JavaScript** — retirer la section `document modal`, `openDuplicates` et le traitement `data-summary-anchor` / `#doublons` ; dans `renderSummary`, les doublons deviennent des lignes « déjà importé, identique à {fichier d'origine} » dans la liste des fichiers non intégrés, sans lien. Nouvelle section `invoice detail` : sélection au clic, à Entrée et aux flèches haut / bas (sans animation) ; `history.replaceState` avec `id` ; chargement de `GET /api/invoices/{id}` ; remplissage des champs via `bindEditing` / `saveField` existants (enregistrement lié à l'identifiant capturé au focus) ; « Confirmer » et « Valider la facture » appellent les routes de la tâche 3 puis mettent à jour la ligne (`data-state`) et le détail ; `?id=` absent de la liste → première ligne.
- [ ] **Step 5 : vérifier** — `python -m pytest -q` passe ; script Playwright sur des données d'exemple : clic sur une ligne → `?id=` dans l'adresse et champs remplis ; flèche bas → ligne suivante ; « Confirmer » → bouton masqué et pastille mise à jour ; `?id=inconnu` → première ligne sélectionnée ; aucun message de console ; pas de défilement horizontal à 1280 et 390 px.
- [ ] **Step 6 : commit** — `git commit -m "Factures : page liste et détail"`.

---

### Task 6 : visionneuse

**Files :**
- Modify : `static/app.js` (section `viewer`), `static/app.css`, `templates/invoices.html` (contenu de `#viewer`)

**Interfaces :**
- Consumes : `invoice:selected` et `#detailFields` (tâche 5) ; `GET /invoices/{id}/pages/{n}.png`, `page_count`, `document_kind`, `uncertain_regions` (tâche 4).
- Produces : dans `#viewer` : `#viewerStage` (conteneur), `#viewerImage`, `#viewerRegions` (calque des cadres `.region[data-field]`), `#zoomOut`, `#zoomIn`, `#zoomFit`, `#zoomLevel`, `#pagePrev`, `#pageNext`, `#pageLabel`, `#nextDoubt`, `#viewerEmpty` ; événement `region:focus` (détail `{field}`) quand un champ douteux reçoit le focus ou le survol.

- [ ] **Step 1 : comportement** — image d'une page (`/pages/{n}.png`) ; transformation unique `translate(x, y) scale(s)` sur un conteneur qui porte l'image et le calque, donc les cadres (positionnés en pourcentages) suivent sans recalcul ; `s` borné à `[0.5, 4]` ; « Ajuster » cadre la page dans la zone ; Ctrl + molette et pincement zooment autour du pointeur ; glisser déplace 1:1 avec `setPointerCapture` en respectant le point de prise, avec une résistance au-delà des bords (`rubberband(overshoot, dimension, 0.55)` de la skill `apple-design`) et un retour par ressort au relâché.
- [ ] **Step 2 : zone douteuse suivante** — parcourt les cadres dans l'ordre (page, puis y) ; change de page si besoin ; anime `translate` et `scale` vers le cadre centré, zoom tel que le cadre occupe 60 % de la largeur, borné à `[1, 4]`. Animation par ressort critique (amortissement 1, réponse 0,35 s) recalculé à chaque image depuis la valeur affichée, donc interruptible par un glisser ou un zoom. `prefers-reduced-motion: reduce` → saut direct.
- [ ] **Step 3 : liens champ ↔ cadre** — survol ou focus d'un champ douteux : son cadre passe en trait plein et plus épais ; clic sur un cadre : focus du champ. Sans fichier : `#viewerEmpty` « Document original non conservé. » ; sans cadre : rien n'est dessiné.
- [ ] **Step 4 : vérifier** — `python -m pytest -q` passe ; script Playwright sur une facture d'exemple à deux pages avec deux cadres : `#zoomIn` change l'échelle affichée ; `#nextDoubt` amène la page du premier cadre et place son centre à moins de 10 % du centre de `#viewerStage` ; un second clic passe au cadre suivant ; glisser déplace l'image ; `#pageNext` change l'image ; aucune erreur de console ; captures à 1280 et 390 px.
- [ ] **Step 5 : commit** — `git commit -m "Factures : visionneuse navigable avec zones douteuses"`.

---

### Task 7 : documentation, vérification et PR

**Files :**
- Modify : `CLAUDE.md` (sections « Deduplication & storage », « Import summary pop-up », « The correction → rule loop », « UI conventions » : visionneuse ; nouvelle mention de `documents.py` dans le tableau des modules)

- [ ] **Step 1 : `CLAUDE.md`** — doublons journalisés dans `import_log` avec leur raison, plus de panneau ni d'ancre `#doublons` ; bilan d'import lu dans le journal ; confirmations (`corrections.kind`) dans la boucle d'apprentissage ; visionneuse en pages rendues avec cadres `uncertain_regions` ; route des pages dans les invariants de sécurité.
- [ ] **Step 2 : données d'exemple** — script temporaire (hors dépôt) : espace avec des PDF générés par PyMuPDF (une et deux pages), factures avec `uncertain_regions`, une facture sans fichier, une en erreur, un lot terminé avec deux doublons dans `import_log`.
- [ ] **Step 3 : captures** — liste et détail à 1280 et 390 px, zone douteuse mise en évidence après `#nextDoubt`, bilan d'import avec doublons.
- [ ] **Step 4 : pousser et ouvrir la PR** — `git push`, puis PR vers `main` par l'API REST (`gh api repos/BenoitPierson/The-bill-please/pulls`), titre « Refonte Brume : page Factures », description avec changements, tests, captures (images commitées dans `docs/superpowers/specs/images/`) et se terminant par :

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01GHDHZs4Bn8jD7j6FrpG3DC
```
