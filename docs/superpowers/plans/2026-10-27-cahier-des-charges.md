# Cahier des charges — plan de rédaction

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Écrire la référence de l'existant de The Bill Please en deux versions :

- un cahier des charges technique en Markdown dans le dépôt ;
- une présentation client / investisseur en document Docs éditable, avec une capture
  d'écran par grande étape.

**Architecture:** La source de vérité est le code de la PR #4 (`origin/claude/refonte-brume-factures`,
qui contient `main`). Chaque affirmation se vérifie contre ce code. Les contrôles automatisables
(identifiants, traçabilité, calculs de coût, rendu Mermaid) sont faits par des scripts jetables
du scratchpad, jamais commités. Les captures sont prises avec Playwright sur un serveur local
avec des données de test.

**Tech Stack:** Markdown + Mermaid (rendu GitHub), Playwright (Python système), mmdc, type
d'artefact Docs.

**Spec:** `docs/superpowers/specs/2026-10-27-cahier-des-charges-design.md`

## Global Constraints

- **Langue :** les deux documents sont en français.
- **Périmètre :** ils décrivent l'existant de `main` + PR #4 au 27 octobre 2026. Pas de
  feuille de route, pas de chiffres de marché, pas de tarification commerciale.
- **Version client :** le modèle y est appelé « l'automate ». Anthropic n'est nommé qu'en
  section 6, Claude qu'en section 8.
- **Chiffres :** chaque chiffre porte sa source et sa date.
- **Coûts :** en dollars, la monnaie du tarif. L'estimation de septembre, en euros, est citée
  telle quelle et marquée comme telle.
- **Fichiers intouchables :**
  - aucune modification du code de l'application ni des trois PDF de `docs/` ;
  - `.env` n'est jamais ouvert, et aucune clé API n'est utilisée.
- **Commits :** `git -c user.name="Claude" -c user.email="noreply@anthropic.com"`, avec les deux
  lignes d'attribution de session.
- **Branche :** `claude/cahier-des-charges`. La PR est ouverte vers `main` avec la mention
  « à fusionner après la PR #4 ».

## Review Focus

1. **Une affirmation vraie sur `main` mais fausse avec la PR #4, ou l'inverse** (panneau des
   doublons, table `duplicates`, `#docModal`). Le lecteur attend la description de l'état
   fusionné : chaque section est vérifiée contre `origin/claude/refonte-brume-factures`.
2. **Un chiffre de septembre devenu faux** :
   - `max_tokens` est passé de 2 048 à 8 192 ;
   - le rendu de l'extraction est à 150 dpi, celui de la visionneuse à 200 dpi ;
   - les lignes de facture ont alourdi la sortie.

   Chaque chiffre repris est revérifié dans le code.
3. **Une exigence de sécurité présentée comme testée alors qu'aucun test du dépôt ne la
   couvre.** Le contrôle de traçabilité (tâche 4) le rend impossible.
4. **Une capture qui montre l'adresse e-mail réelle d'Océane ou une clé.** Les captures
   n'utilisent que le compte de test `demo@exemple.fr`, et la tâche 5 les inspecte une à une.
5. **Un diagramme Mermaid qui ne s'affiche pas sur GitHub.** Il est rendu par `mmdc` avant le
   commit (tâche 2).

---

### Task 1: Cahier technique — sections 1 à 4 (périmètre, acteurs, exigences)

**Files:**
- Create: `docs/cahier-des-charges-technique.md`

**Interfaces:**
- Produces: identifiants `EF-IMP-n`, `EF-EXT-n`, `EF-ACC-n`, `EF-FAC-n`, `EF-PRO-n`, `EF-REG-n`,
  `EF-ADM-n`, `ENF-PERF-n`, `ENF-STO-n`, `ENF-SEC-n`, `ENF-ISO-n`, `ENF-COMP-n`, `ENF-UI-n`. Chaque
  exigence s'écrit sur une ligne de la forme `- **EF-IMP-1** — L'application doit …`. La tâche 4
  les relève avec l'expression `\*\*(E[N]?F-[A-Z]+-\d+)\*\*`.

- [ ] **Step 1: Écrire le contrôle des identifiants** (scratchpad `docs_check.py`, sous-commande `ids`).
  - Il échoue si un identifiant apparaît deux fois en tête de ligne, si un domaine de la liste
    ci-dessus n'a aucune exigence, ou si une ligne d'exigence ne contient pas « doit ».
- [ ] **Step 2: Lancer le contrôle sur le fichier absent.** Attendu : échec « fichier introuvable ».
- [ ] **Step 3: Rédiger les sections 1 à 4** à partir du code de la PR #4 (`git show origin/claude/refonte-brume-factures:<fichier>`)
  et de `CLAUDE.md` de cette même branche.
  - La section 1 contient le tableau « ce qui a changé depuis les PDF de septembre » de la spec.
  - En section 4, chaque invariant de sécurité de `CLAUDE.md` devient une exigence `ENF-SEC`.
- [ ] **Step 4: Relancer le contrôle.** Attendu : `ids: OK (<n> exigences, 13 domaines)`.
- [ ] **Step 5: Commit** — `Cahier technique : périmètre, acteurs et exigences`.

### Task 2: Cahier technique — sections 5 et 6 (architecture, hypothèses et limites)

**Files:**
- Modify: `docs/cahier-des-charges-technique.md`

**Interfaces:**
- Consumes: les identifiants de la tâche 1. La section 6 peut renvoyer à une exigence par son
  identifiant.

- [ ] **Step 1: Rédiger la section 5.**
  - Tableau des modules, y compris `documents.py`, `products.py` et `dashboard.py`.
  - Parcours d'une facture en diagramme Mermaid `sequenceDiagram`.
  - Modèle de données : une ligne par table de `db.SCHEMA` (branche PR #4), avec ses colonnes
    clés.
  - Dépendance à l'API : `MODEL`, `RULE_MODEL`, réflexion désactivée, `max_tokens=8192`,
    `max_retries=6`, cache du système, `extra_body`.
- [ ] **Step 2: Vérifier le modèle de données contre le schéma.**
  - Le contrôle `docs_check.py tables` compare les tables citées en section 5 avec les
    `CREATE TABLE` de `db.py` de la branche PR #4.
  - Attendu : `tables: OK`, aucune table manquante ni inventée.
- [ ] **Step 3: Rendre le Mermaid.**
  - Extraire le bloc, puis lancer `mmdc -i seq.mmd -o seq.svg`.
  - Attendu : un SVG produit, sans erreur de syntaxe.
- [ ] **Step 4: Rédiger la section 6.**
  - Les « Key assumptions » de `CLAUDE.md`.
  - Les petits défauts différés de la PR #4 (la liste de sa relecture finale).
  - Le manque de la suite de sécurité.
- [ ] **Step 5: Commit** — `Cahier technique : architecture, hypothèses et limites`.

### Task 3: Coût par facture et capacité restante (section 7)

**Files:**
- Modify: `docs/cahier-des-charges-technique.md`

**Interfaces:**
- Produces: deux valeurs, `cout_bas_usd` et `cout_haut_usd` par facture, plus le tableau de
  capacité. La tâche 6 les reprend telles quelles, sans les recalculer.

- [ ] **Step 1: Relever le tarif public de `claude-sonnet-5`** (entrée, sortie, écriture et lecture du cache, en $ par million de jetons).
  - Source : la page de tarifs d'Anthropic, lue avec WebFetch ou WebSearch.
  - Noter l'URL et la date.
  - Si le modèle n'y figure pas, s'arrêter et le signaler à Océane plutôt que de supposer un
    tarif.
- [ ] **Step 2: Écrire le calcul** (scratchpad `cost.py`), avec ses hypothèses en constantes.
  - **Cas bas :** 1 page = 2 900 jetons d'image ; système de 1 270 jetons lu en cache ;
    sortie de 600 jetons.
  - **Cas haut :** 3 pages = 8 700 jetons ; système de 6 900 jetons lu en cache ; sortie de
    3 000 jetons (40 lignes).
  - Vérifier que la sortie retombe dans la fourchette documentée d'« un demi-centime à un
    centime ». Sinon, ajuster les jetons de sortie et noter l'écart dans le document.
  - Capacité pour 10 $, 50 $ et 100 $ : `floor(crédit / coût)`.
- [ ] **Step 3: Lancer le calcul.**
  - Attendu : deux coûts par facture et six nombres de factures, tous affichés.
  - Contrôle de cohérence : `cout_bas < cout_haut`.
- [ ] **Step 4: Rédiger la section 7.**
  - Hypothèses, tarif daté, fourchette et tableau.
  - Comparaison avec « 10 à 12 € pour 1 000 factures » (septembre, avant l'extraction des
    lignes).
  - Formule `factures restantes ≈ crédit restant ÷ coût par facture`.
  - Où lire le crédit : sur la Console Anthropic, page de facturation.
  - Renvoi à la future mesure dans l'application.
- [ ] **Step 5: Commit** — `Cahier technique : coût par facture et capacité`.

### Task 4: Traçabilité (section 8)

**Files:**
- Modify: `docs/cahier-des-charges-technique.md`

**Interfaces:**
- Consumes: les identifiants de la tâche 1.
- Produces: un tableau `| Exigence | Test(s) |` où chaque test s'écrit `tests/<fichier>.py::<fonction>`,
  ou bien **non couverte**.

- [ ] **Step 1: Écrire le contrôle `docs_check.py trace`.** Il échoue :
  - si un identifiant des sections 3-4 n'a pas de ligne dans le tableau ;
  - si le tableau cite un identifiant inexistant ;
  - si un test cité n'apparaît pas dans `pytest --collect-only -q`, exécuté sur une copie de
    travail de la branche PR #4 avec le venv du scratchpad.
- [ ] **Step 2: Lancer le contrôle avant le tableau.** Attendu : échec, avec la liste des exigences sans ligne.
- [ ] **Step 3: Rédiger la section 8.**
  - Une exigence n'est rattachée à un test que si ce test vérifie vraiment le comportement
    énoncé (lire le test, pas seulement son nom).
  - Ajouter une note sur la suite de sécurité absente.
- [ ] **Step 4: Relancer le contrôle.** Attendu : `trace: OK (<c> couvertes, <n> non couvertes)`.
- [ ] **Step 5: Commit** — `Cahier technique : traçabilité des exigences`.

### Task 5: Captures manquantes

**Files:**
- Create: `docs/superpowers/specs/images/2026-10-27-presentation-import.png`
- Create: `docs/superpowers/specs/images/2026-10-27-presentation-import-en-cours.png`
- Create: `docs/superpowers/specs/images/2026-10-27-presentation-produits.png`

**Interfaces:**
- Produces: ces trois images. La tâche 6 les insère dans le document Docs avec les cinq
  existantes de la spec.

- [ ] **Step 1: Préparer le serveur de capture.**
  - Faire un worktree de `origin/claude/refonte-brume-factures` dans le scratchpad.
  - Lancer `seed_factures.py`, puis ajouter des lignes de facture (`invoice_lines`) pour que
    la page Produits montre une dérive.
  - Le serveur tourne avec un `DATA_DIR` du scratchpad.
  - Pour l'import en cours, un lanceur du scratchpad remplace `extraction.extract_invoice` par
    une fonction qui attend 2 s et renvoie un résultat de test. Aucun appel API.
- [ ] **Step 2: Écrire le script de capture** (scratchpad `capture_presentation.py`, viewport 1280×900).
  1. Panneau d'import ouvert : `#importBtn`.
  2. Import en cours : déposer une archive de 20 PDF de test, puis attendre que la
     progression et le temps restant soient visibles.
  3. Page `/products`.
- [ ] **Step 3: Lancer le script.** Attendu : trois PNG, et aucune erreur console.
- [ ] **Step 4: Inspecter chaque image** (outil Read).
  - Attendu : elle montre ce que dit son nom.
  - Aucune adresse autre que `demo@exemple.fr` n'apparaît, et aucune clé.
- [ ] **Step 5: Commit** — `Captures pour la présentation : import et produits`.

### Task 6: Présentation client / investisseur (document Docs éditable)

**Files:**
- Aucun fichier du dépôt. Un artefact Docs est créé.

**Interfaces:**
- Consumes:
  - les coûts et le tableau de capacité de la tâche 3 ;
  - les huit captures (trois de la tâche 5, cinq de la spec) ;
  - les sections 3-4 du cahier technique comme source des affirmations.

- [ ] **Step 1: Créer le document** avec le type Docs : `Artifact` quickstart `intent: "document"`, puis les instructions du type.
  - Titre « The Bill Please — présentation ».
  - Un squelette avec les 8 sections de la spec.
- [ ] **Step 2: Rédiger les sections 1, 2 et 4 à 8.**
  - Section 5 : les chiffres du cahier technique, chacun avec sa date.
  - Section 6 : reprend la note RGPD de septembre (engagements Anthropic, transfert hors UE,
    ce qui reste à la charge de l'éditeur), avec ses sources et l'avertissement « pas un avis
    juridique ».
- [ ] **Step 3: Rédiger la section 3.**
  - Une sous-partie par étape (importer, l'automate lit, vérifier, analyser), avec ses
    captures dans l'ordre du tableau de la spec et une légende de 1 à 2 phrases.
  - La vue téléphone en encadré.
  - La mention « données de test ».
- [ ] **Step 4: Relire le document publié.**
  - Le relire en entier.
  - Chercher « Claude » et « Anthropic » : attendu, seulement en sections 8 et 6.
  - Chercher les termes techniques (`SQLite`, `API` hors section 6 et 8, `JSON`) : attendu,
    aucun.
  - Vérifier que les huit images s'affichent.

### Task 7: Relecture indépendante et PR

**Files:**
- Modify: `docs/cahier-des-charges-technique.md` (corrections uniquement)

- [ ] **Step 1: Lancer un relecteur indépendant** sur le modèle le plus capable.
  - Entrées : la spec, le cahier technique et le texte du document Docs.
  - Consigne : confronter chaque affirmation au code de `origin/claude/refonte-brume-factures`
    et lister les affirmations fausses, invérifiables, ou qui contredisent l'autre document.
- [ ] **Step 2: Corriger chaque point retenu** dans les deux documents.
  - Relancer `docs_check.py ids tables trace`. Attendu : trois `OK`.
- [ ] **Step 3: Commit, push, puis ouvrir la PR** « Cahier des charges technique et présentation » vers `main`, par l'API REST.
  - Le corps contient le lien du document Docs et la mention « à fusionner après la PR #4 ».
- [ ] **Step 4: Vérifier l'aperçu GitHub du cahier technique sur la branche** : `gh api repos/BenoitPierson/The-bill-please/contents/docs/cahier-des-charges-technique.md?ref=claude/cahier-des-charges -H "Accept: application/vnd.github.html"`.
  - Attendu : les tableaux et le diagramme Mermaid apparaissent dans le HTML rendu.

