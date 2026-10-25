# Refonte Brume, livraison 1 (socle et accueil) — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** remplacer le socle visuel par la palette Brume et reconstruire l'accueil (gros chiffre du dernier mois complet, évolution sur 12 mois, dernier import, alertes de prix, heatmap avec infobulle, 3 dernières factures importées).

**Architecture :** les calculs de date, de devise et de sélection vivent dans un nouveau module pur `dashboard.py`, testé sans base. `db.py` reçoit des requêtes ciblées, `charts.py` adapte la géométrie (mois en cours, infobulle de la heatmap). La route `/dashboard` de `app.py` assemble le tout ; le rendu reste du Jinja côté serveur, un CSS et un JS sans bundler.

**Tech Stack :** Python 3.8 (Anaconda), FastAPI, Jinja2, SQLite, CSS et JavaScript sans dépendance, pytest.

**Spec :** `docs/superpowers/specs/2026-10-25-refonte-brume-accueil-design.md`

## Global Constraints

- Compatibilité Python 3.8 : `from __future__ import annotations` en tête de module ; dans les signatures de routes de `app.py`, uniquement `typing.List` / `typing.Optional`.
- Aucun texte d'interface ne nomme le modèle : dire « l'automate ».
- Aucun texte issu d'une facture n'est inséré via `innerHTML` : construire des nœuds et utiliser `textContent`.
- Aucun script inline ; ressources servies par `static_url('…')`, jamais `/static/…` en dur.
- Thème clair unique (`color-scheme: light`) ; conserver `[hidden] { display: none !important }`.
- Une seule couleur de bouton ; le bleu (`--series-1`) est réservé aux liens et au focus.
- Aucun total qui mélange deux devises.
- Montants en erreur (`error IS NOT NULL`) exclus de tous les montants de l'accueil.
- Police : Instrument Sans, paquet `@fontsource/instrument-sans@5.3.0`, fichiers dans `static/fonts/`.
- Mouvement : seules `transform` et `opacity` animées ; pas de `transition: all` ; survols sous `@media (hover: hover) and (pointer: fine)` ; `prefers-reduced-motion: reduce` → fondus uniquement.
- Seuil d'alerte de prix : `products.DEFAULT_ALERT_THRESHOLD` (25).
- Chaque commit se termine par :
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` et
  `Claude-Session: https://claude.ai/code/session_01GHDHZs4Bn8jD7j6FrpG3DC`.

## Review Focus

- Un mois où deux devises ont autant de factures : la devise principale doit être stable (départage au montant, puis ordre alphabétique) — test dans la tâche 1.
- Le 1er janvier : le dernier mois complet est décembre de l'année précédente, et la fenêtre de 12 mois traverse l'année — tests dans la tâche 1.
- Une facture en erreur ou sans date valide ne doit compter ni dans le gros chiffre, ni dans la série, ni dans la heatmap — test dans la tâche 2.
- Un nom de fournisseur contenant `<b>` ou `"` doit s'afficher littéralement sur l'accueil — test dans la tâche 5.
- Une base sans aucune facture ni lot : l'accueil répond 200 avec l'état vide et le lien d'import — test dans la tâche 5.

---

## Structure des fichiers

| Fichier | Rôle |
| --- | --- |
| `dashboard.py` (nouveau) | Fonctions pures : dernier mois complet, fenêtre de mois, devise principale, sélection des alertes, libellés de mois |
| `db.py` | Requêtes de l'accueil |
| `charts.py` | Paliers de la heatmap, mois en cours, données d'infobulle |
| `app.py` | Route `/dashboard` |
| `templates/base.html`, `templates/dashboard.html` | Navigation, accueil |
| `static/app.css`, `static/app.js`, `static/fonts/` | Socle visuel, interactions |
| `requirements-dev.txt`, `tests/` (nouveaux) | Outillage de test |

---

### Task 1 : outillage de test et calculs purs de l'accueil

**Files :**
- Create : `requirements-dev.txt`, `tests/__init__.py`, `tests/conftest.py`, `dashboard.py`, `tests/test_dashboard.py`

**Interfaces :**
- Produces :
  - `last_complete_month(today: date) -> Tuple[int, int]`
  - `month_window(today: date, months: int = 12) -> List[str]` — périodes `"YYYY-MM"`, de la plus ancienne au mois en cours inclus
  - `period(year: int, month: int) -> str` — `"2026-09"`
  - `month_name(year: int, month: int) -> str` — `"septembre 2026"`
  - `main_currency(rows: Sequence[Dict[str, Any]]) -> Optional[str]` — lignes `{"currency", "amount", "invoice_count"}`
  - `top_price_alerts(summary: Sequence[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]` — lignes de `products.summarise`
  - fixture pytest `tenant` (slug d'un espace isolé dans `tmp_path`)

- [ ] **Step 1 : outillage**

`requirements-dev.txt` :
```
-r requirements.txt
pytest>=7.4,<8.4
httpx>=0.27,<0.28
# Starlette >= 0.47 refuse l'ancienne signature de TemplateResponse utilisée par app.py.
# Correctif sur une branche séparée ; en attendant, borne ici pour que les tests de route tournent.
starlette>=0.40,<0.47
```

`tests/conftest.py` : fixture `tenant(tmp_path, monkeypatch)` qui fait `monkeypatch.setattr(tenants, "TENANTS_DIR", tmp_path / "tenants")`, vide `db._initialised`, crée l'espace `"test"` avec `tenants.create("test")` et renvoie `"test"`.

- [ ] **Step 2 : écrire les tests qui échouent** (`tests/test_dashboard.py`)

```python
def test_last_complete_month_regular():
    assert last_complete_month(date(2026, 10, 25)) == (2026, 9)

def test_last_complete_month_january():
    assert last_complete_month(date(2027, 1, 1)) == (2026, 12)

def test_month_window_includes_current_month_and_crosses_year():
    window = month_window(date(2026, 3, 4))
    assert len(window) == 12
    assert window[0] == "2025-04" and window[-1] == "2026-03"

def test_month_name():
    assert month_name(2026, 9) == "septembre 2026"

def test_main_currency_by_count():
    rows = [{"currency": "KES", "amount": 10.0, "invoice_count": 5},
            {"currency": "USD", "amount": 900.0, "invoice_count": 2}]
    assert main_currency(rows) == "KES"

def test_main_currency_tie_broken_by_amount_then_name():
    rows = [{"currency": "USD", "amount": 50.0, "invoice_count": 3},
            {"currency": "EUR", "amount": 80.0, "invoice_count": 3}]
    assert main_currency(rows) == "EUR"
    same = [{"currency": "USD", "amount": 50.0, "invoice_count": 3},
            {"currency": "EUR", "amount": 50.0, "invoice_count": 3}]
    assert main_currency(same) == "EUR"

def test_main_currency_empty():
    assert main_currency([]) is None

def test_top_price_alerts_keeps_three_highest_drifts():
    summary = [{"alert": True, "drift": 26.0}, {"alert": False, "drift": 90.0},
               {"alert": True, "drift": 31.0}, {"alert": True, "drift": 27.0},
               {"alert": True, "drift": 40.0}]
    assert [a["drift"] for a in top_price_alerts(summary)] == [40.0, 31.0, 27.0]
```

- [ ] **Step 3 : vérifier l'échec**

Run : `python -m pytest tests/test_dashboard.py -q`
Expected : erreurs d'import (`dashboard` absent).

- [ ] **Step 4 : implémenter `dashboard.py`**

Noms de mois en minuscules français complets (`janvier` … `décembre`). `main_currency` ignore une devise vide (`""`) sauf si c'est la seule ; tri par `(-invoice_count, -amount, currency)`.

- [ ] **Step 5 : vérifier le succès**

Run : `python -m pytest tests/test_dashboard.py -q`
Expected : `8 passed`.

- [ ] **Step 6 : commit** — `git add requirements-dev.txt tests dashboard.py` puis `git commit -m "Accueil : calculs purs et outillage de test"`.

---

### Task 2 : requêtes de l'accueil dans `db.py`

**Files :**
- Modify : `db.py` (ajouts après `dashboard_stats`)
- Test : `tests/test_db_home.py`

**Interfaces :**
- Consumes : fixture `tenant` (tâche 1).
- Produces :
  - `totals_by_currency(slug: str, first_period: str, last_period: str) -> List[Dict[str, Any]]` — `{"currency", "amount", "invoice_count"}` sur `substr(invoice_date,1,7)` entre les deux bornes incluses ; `currency` vaut `""` si nulle.
  - `monthly_series(slug: str, periods: Sequence[str], currency: Optional[str]) -> List[Dict[str, Any]]` — une ligne `{"period", "amount", "invoice_count"}` par période demandée, à `0` si absente ; filtrée sur `currency` si fournie.
  - `latest_batch(slug: str) -> Optional[Dict[str, Any]]` — ligne `batches` la plus récente par `started_at`.
  - `latest_invoices(slug: str, limit: int = 3) -> List[Dict[str, Any]]` — `ORDER BY created_at DESC`, avec `uncertain_fields` et `edited_fields` décodés en listes.
  - `count_uncertain(slug: str) -> int` — factures sans erreur avec `uncertain_fields != '[]'`.
  - `heatmap_rows(slug: str) -> List[Dict[str, Any]]` — `{"day", "supplier", "amount", "invoice_count", "invoice_numbers"}`, `invoice_numbers` = liste des numéros non vides (via `GROUP_CONCAT(invoice_number, char(31))`).

Toutes excluent `error IS NOT NULL` et les dates de longueur incorrecte (7 pour un mois, 10 pour un jour).

- [ ] **Step 1 : écrire les tests qui échouent**

Helper local `add(slug, **fields)` appelant `db.insert_invoice` avec `filename="f.pdf"`.

```python
def test_totals_by_currency_excludes_errors_and_bad_dates(tenant):
    add(tenant, invoice_date="2026-09-03", total_amount=100.0, currency="KES")
    add(tenant, invoice_date="2026-09-20", total_amount=50.0, currency="USD")
    add(tenant, invoice_date="2026-09-21", total_amount=999.0, currency="KES", error="Erreur API : x")
    add(tenant, invoice_date="sept 2026", total_amount=999.0, currency="KES")
    rows = {r["currency"]: r for r in db.totals_by_currency(tenant, "2026-09", "2026-09")}
    assert rows["KES"]["amount"] == 100.0 and rows["KES"]["invoice_count"] == 1
    assert rows["USD"]["amount"] == 50.0

def test_monthly_series_fills_missing_months(tenant):
    add(tenant, invoice_date="2026-08-10", total_amount=10.0, currency="KES")
    series = db.monthly_series(tenant, ["2026-08", "2026-09", "2026-10"], "KES")
    assert [(r["period"], r["amount"]) for r in series] == [
        ("2026-08", 10.0), ("2026-09", 0.0), ("2026-10", 0.0)]

def test_latest_invoices_by_import_order(tenant):
    for n in range(4):
        add(tenant, invoice_number="N{}".format(n), invoice_date="2026-01-0{}".format(n + 1))
    assert [r["invoice_number"] for r in db.latest_invoices(tenant)] == ["N3", "N2", "N1"]

def test_heatmap_rows_collects_numbers(tenant):
    add(tenant, supplier_name="Bidco", invoice_date="2026-09-03", total_amount=5.0, invoice_number="A1")
    add(tenant, supplier_name="Bidco", invoice_date="2026-09-03", total_amount=7.0, invoice_number="A2")
    (row,) = db.heatmap_rows(tenant)
    assert row["amount"] == 12.0 and row["invoice_count"] == 2
    assert sorted(row["invoice_numbers"]) == ["A1", "A2"]

def test_latest_batch_none_then_most_recent(tenant):
    assert db.latest_batch(tenant) is None
    db.create_batch(tenant, "a.zip", 1)
    second = db.create_batch(tenant, "b.zip", 1)
    assert db.latest_batch(tenant)["id"] == second
```

`created_at` est à la seconde : dans `test_latest_invoices_by_import_order`, insérer avec un `created_at` croissant en passant par une mise à jour SQL directe après insertion, ou départager par `rowid DESC` dans la requête (retenu : `ORDER BY created_at DESC, rowid DESC`). Même départage pour `latest_batch` (`started_at DESC, rowid DESC`).

- [ ] **Step 2 : vérifier l'échec** — `python -m pytest tests/test_db_home.py -q` → `AttributeError` sur `db.totals_by_currency`.
- [ ] **Step 3 : implémenter les six fonctions** dans `db.py`, avec `connect(slug)` comme les autres requêtes.
- [ ] **Step 4 : vérifier le succès** — `python -m pytest -q` → tous les tests passent.
- [ ] **Step 5 : commit** — `git commit -m "Accueil : requêtes dédiées dans db.py"`.

---

### Task 3 : géométrie et données d'infobulle dans `charts.py`

**Files :**
- Modify : `charts.py` (`HEAT_STOPS`, `monthly_columns`, `daily_heatmap`)
- Test : `tests/test_charts.py`

**Interfaces :**
- Consumes : lignes de `db.monthly_series` et `db.heatmap_rows` (tâche 2).
- Produces :
  - `monthly_columns(rows, current_period: Optional[str] = None)` — chaque barre gagne `"is_current": bool` et `"period": str` ; le pic se calcule hors mois en cours si au moins un autre mois a un montant.
  - `daily_heatmap(rows, max_days=45, max_suppliers=12)` — chaque cellule expose `fill`, `supplier`, `date_text` (`day_label`), `amount_text`, `count`, `numbers` (liste, vide si plus de 3), `day_total_text` (somme du jour, tous fournisseurs y compris masqués), `month_share_text` (`format_percent` de la part du jour dans le mois civil du fournisseur, calculée sur toutes ses lignes du mois). Les clés `fill_abs`, `fill_rel`, `value_rel` et `legend[*].rel_label` disparaissent ; `legend` garde `fill` et `abs_label`.
  - `HEAT_STOPS` désaturé, toujours vert → rouge.

- [ ] **Step 1 : écrire les tests qui échouent**

```python
def _lightness(rgb):
    r, g, b = (c / 255 for c in rgb)
    return (max(r, g, b) + min(r, g, b)) / 2

def test_heat_stops_lightness_strictly_decreases():
    values = [_lightness(rgb) for _, rgb in charts.HEAT_STOPS]
    assert all(a > b for a, b in zip(values, values[1:]))

def test_heat_stops_go_from_green_to_red():
    first, last = charts.HEAT_STOPS[0][1], charts.HEAT_STOPS[-1][1]
    assert first[1] > first[0] and last[0] > last[1]

def test_monthly_columns_marks_current_month():
    rows = [{"period": "2026-09", "amount": 100.0, "invoice_count": 3},
            {"period": "2026-10", "amount": 20.0, "invoice_count": 1}]
    bars = charts.monthly_columns(rows, current_period="2026-10")["bars"]
    assert [b["is_current"] for b in bars] == [False, True]

def test_heatmap_tooltip_data():
    rows = [{"day": "2026-09-03", "supplier": "Bidco", "amount": 30.0, "invoice_count": 2, "invoice_numbers": ["A1", "A2"]},
            {"day": "2026-09-10", "supplier": "Bidco", "amount": 70.0, "invoice_count": 1, "invoice_numbers": ["A3"]},
            {"day": "2026-09-03", "supplier": "Freshchips", "amount": 20.0, "invoice_count": 1, "invoice_numbers": []}]
    cell = next(c for c in charts.daily_heatmap(rows)["cells"]
                if c["supplier"] == "Bidco" and c["date_text"].startswith("3 "))
    assert cell["numbers"] == ["A1", "A2"]
    assert cell["day_total_text"] == charts.format_amount(50.0)
    assert cell["month_share_text"] == charts.format_percent(30.0)
    assert "fill_rel" not in cell

def test_heatmap_hides_numbers_beyond_three():
    rows = [{"day": "2026-09-03", "supplier": "X", "amount": 1.0, "invoice_count": 4,
             "invoice_numbers": ["1", "2", "3", "4"]}]
    assert charts.daily_heatmap(rows)["cells"][0]["numbers"] == []
```

- [ ] **Step 2 : vérifier l'échec** — `python -m pytest tests/test_charts.py -q`.
- [ ] **Step 3 : implémenter** — nouveaux paliers (0 → 1) : `(226, 238, 222)`, `(196, 218, 170)`, `(222, 196, 128)`, `(200, 128, 92)`, `(150, 70, 58)` ; ajuster si le test de luminosité échoue, sans quitter vert → rouge. `HEAT_DARK_FROM` recalé pour que l'encre blanche ne s'applique qu'aux deux paliers les plus sombres.
- [ ] **Step 4 : vérifier le succès** — `python -m pytest -q`.
- [ ] **Step 5 : commit** — `git commit -m "Accueil : mois en cours et infobulle de la heatmap"`.

---

### Task 4 : socle visuel (police, jetons, navigation)

**Files :**
- Create : `static/fonts/instrument-sans-latin-{400,500,600,700}-normal.woff2`, `static/fonts/OFL.txt`
- Modify : `static/app.css` (bloc `:root`, typographie, `.topbar`, `.tabs`, boutons), `templates/base.html` (navigation), `static/app.js` (filet au défilement)

**Interfaces :**
- Produces : jetons CSS `--plane #eff3f6`, `--surface #ffffff`, `--ink #1b2830`, `--ink-secondary #3a4a54`, `--ink-muted #64747e`, `--grid #e2e9ee`, `--series-1 #467a91`, `--series-1-soft #b2cfdb`, `--apricot #a66c50`, `--uncertain #f5e5d2`, `--edited #dcebe1`, `--font 'Instrument Sans', system-ui, -apple-system, "Segoe UI", sans-serif`, `--ease-out cubic-bezier(0.23, 1, 0.32, 1)` ; classe `.topbar.is-scrolled` posée par `app.js`.

- [ ] **Step 1 : récupérer la police** — `npm pack @fontsource/instrument-sans@5.3.0` dans un dossier temporaire, extraire, copier les quatre fichiers `files/instrument-sans-latin-*-normal.woff2` et la licence OFL dans `static/fonts/`. Vérifier : `ls static/fonts` liste 5 fichiers.
- [ ] **Step 2 : jetons et `@font-face`** — remplacer les valeurs de `:root` (noms existants conservés, `--apricot` ajouté), déclarer les quatre graisses avec `font-display: swap` et des URL relatives `fonts/…` (le CSS est servi depuis `/static/`).
- [ ] **Step 3 : typographie** — échelle en `rem` ; gros chiffres `letter-spacing: -0.02em; line-height: 1.05` ; titres `-0.01em; 1.2` ; texte `0; 1.5` ; étiquettes en capitales `0.04em` ; `font-variant-numeric: tabular-nums` sur montants et tableaux.
- [ ] **Step 4 : navigation** — `base.html` : libellés « Tableau de bord », « Factures », « Produits » ; sélecteur en segments. CSS : `.topbar` collante, `background: rgb(255 255 255 / 0.72)`, `backdrop-filter: blur(20px) saturate(180%)`, aucune bordure ; `.topbar.is-scrolled` ajoute `box-shadow: 0 1px 0 var(--grid)`. Variantes `@media (prefers-reduced-transparency: reduce)` et `@media (prefers-contrast: more)` : fond `var(--surface)` opaque, sans flou, bordure `1px solid var(--ink-muted)` pour le contraste.
- [ ] **Step 5 : boutons** — `.btn:active { transform: scale(0.97) }` avec `transition: transform 100ms var(--ease-out)` ; survols sous `@media (hover: hover) and (pointer: fine)` ; `@media (prefers-reduced-motion: reduce)` neutralise le `transform`.
- [ ] **Step 6 : filet au défilement** — dans `app.js`, un écouteur `scroll` passif bascule `is-scrolled` quand `window.scrollY > 4`.
- [ ] **Step 7 : vérifier** — lancer l'application (voir tâche 6, données d'exemple), ouvrir `/invoices` et `/products` : navigation en français, police chargée (onglet Réseau sans erreur 404 sur `/static/fonts/`), aucune erreur de politique de sécurité dans la console. `python -m pytest -q` passe toujours.
- [ ] **Step 8 : commit** — `git add static templates/base.html` puis `git commit -m "Socle Brume : police, couleurs et navigation"`.

---

### Task 5 : route et gabarit de l'accueil

**Files :**
- Modify : `app.py` (route `dashboard`), `templates/dashboard.html`, `static/app.css` (styles de l'accueil), `static/app.js` (retrait de la bascule, nouvelle infobulle)
- Test : `tests/test_home_route.py`

**Interfaces :**
- Consumes : tâches 1 à 3.
- Produces : contexte de gabarit de `/dashboard` :
  - `headline` : `{"month_label", "empty", "amount_text", "currency", "others": [{"amount_text", "currency"}], "invoice_count"}`
  - `uncertain_count: int`
  - `monthly` (sortie de `monthly_columns`) et `monthly_other_currencies: List[str]`
  - `last_batch` : `None` ou la sortie de `db.batch_summary`, plus `"progress"` (sortie de `pipeline.batch_progress`) si le lot tourne
  - `alerts` (sortie de `top_price_alerts`)
  - `heatmap` (sortie de `daily_heatmap`)
  - `recent` (sortie de `db.latest_invoices`)

- [ ] **Step 1 : écrire les tests qui échouent**

Fixture `client(tenant, monkeypatch)` dans le fichier de test : `TestClient(app.app)`, avec `app.DEFAULT_TENANT` **et** `tenants.DEFAULT_TENANT` monkeypatchés à `"test"` (l'hôte `testserver` retombe sur l'espace par défaut), puis connexion via `db.create_user(tenant, "a@b.fr", auth.hash_password("motdepasse1"))` et `POST /login`. Date figée : `monkeypatch.setattr(app, "_today", lambda: date(2026, 10, 25))`.

```python
def test_home_empty_state(client):
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert "Importer des factures" in page.text

def test_home_shows_last_complete_month_only(client, tenant):
    add(tenant, invoice_date="2026-09-12", total_amount=1200.0, currency="KES")
    add(tenant, invoice_date="2026-10-02", total_amount=999.0, currency="KES")
    page = client.get("/dashboard").text
    assert "septembre 2026" in page
    assert charts.format_amount(1200.0) in page

def test_home_escapes_supplier_names(client, tenant):
    add(tenant, supplier_name='<b>Evil "Co"</b>', invoice_date="2026-09-12",
        total_amount=10.0, currency="KES")
    page = client.get("/dashboard").text
    assert "<b>Evil" not in page and "&lt;b&gt;Evil" in page

def test_home_other_currency_is_a_chip_not_a_sum(client, tenant):
    add(tenant, invoice_date="2026-09-12", total_amount=100.0, currency="KES")
    add(tenant, invoice_date="2026-09-13", total_amount=100.0, currency="KES")
    add(tenant, invoice_date="2026-09-14", total_amount=40.0, currency="USD")
    page = client.get("/dashboard").text
    assert charts.format_amount(200.0) in page and charts.format_amount(240.0) not in page
```

- [ ] **Step 2 : vérifier l'échec** — `python -m pytest tests/test_home_route.py -q`.
- [ ] **Step 3 : route** — fonction `_today() -> date` (renvoie `date.today()`, monkeypatchable) ; `_home_context(slug: str, today: date) -> Dict[str, Any]` assemble les clés ci-dessus ; la route `dashboard` ne lit plus de filtres. La série prend `month_window(today)`, sa devise est `main_currency(totals_by_currency(slug, window[0], window[-1]))`, puis on retire les mois en tête dont le montant est nul (le mois en cours reste toujours).
- [ ] **Step 4 : gabarit** — disposition de la spec (grille `1.7fr 1fr`, empilée sous 900 px). Filtres, graphique fournisseurs, TVA, nombre de fournisseurs, bandeau devises et bascule absolu / relatif retirés. Mois en cours : barre en `var(--series-1-soft)` à 50 % d'opacité avec la mention « en cours ». Cellules de la heatmap : `fill`, et attributs `data-date`, `data-supplier`, `data-amount`, `data-count`, `data-numbers` (joints par « , »), `data-day-total`, `data-share`, tous échappés par Jinja. Ligne des 3 factures : lien vers `/invoices/{id}/file` si `stored_name`. Textes d'état : « Aucune facture en {mois} », « Aucune hausse au-delà de 25 % », « Importer des factures » (lien `/invoices`).
- [ ] **Step 5 : infobulle** — dans `app.js`, retirer le bloc `heatCard` (bascule) ; pour `.heat-cell`, construire l'infobulle par nœuds : ligne forte « date · fournisseur », puis « montant · N facture(s) », « n° A1, A2 » si présent, « Total du jour : … », « {part} de son mois ». Ancrage : `transform-origin` côté case ; entrée `opacity` 0 → 1 et `scale(0.97)` → `1` en 150 ms `var(--ease-out)` ; une infobulle déjà visible change de contenu sans réanimer. Réduit sous `prefers-reduced-motion`.
- [ ] **Step 6 : vérifier le succès** — `python -m pytest -q` → tous les tests passent.
- [ ] **Step 7 : commit** — `git commit -m "Accueil Brume : nouvelle disposition et infobulle"`.

---

### Task 6 : vérification visuelle et PR

**Files :**
- Aucun fichier du dépôt (script d'amorçage dans un dossier temporaire hors dépôt).

- [ ] **Step 1 : données d'exemple** — script temporaire qui crée un espace dans un `DATA_DIR` temporaire, un compte, environ 120 factures sur 13 mois (deux devises, quelques champs incertains et corrigés, deux erreurs), des lignes de produits avec une hausse au-delà de 25 %, et un lot terminé.
- [ ] **Step 2 : lancer** — `DATA_DIR=<tmp> python -m uvicorn app:app --port 8000` ; `curl -s localhost:8000/healthz` répond `{"status":"ok", …}`.
- [ ] **Step 3 : captures** — avec Playwright, connexion puis captures de `/dashboard` à 1280 px et 390 px de large. Contrôler : pas de défilement horizontal de la page, pastille de devise présente, barre « en cours », infobulle au survol d'une case (capture après `hover`), navigation translucide.
- [ ] **Step 4 : pousser et ouvrir la PR** — `git push` puis `gh pr create --base main --head claude/refonte-brume-accueil` avec un titre « Refonte Brume : socle visuel et accueil » et une description qui liste les changements, les tests ajoutés, les captures, et se termine par :

```
🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01GHDHZs4Bn8jD7j6FrpG3DC
```
