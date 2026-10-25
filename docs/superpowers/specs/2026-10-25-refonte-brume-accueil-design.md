# Refonte « Brume » — livraison 1 : socle visuel et accueil

Date : 2026-10-25
Statut : en relecture
Branche : `claude/refonte-brume-accueil` (créée depuis `origin/main`)

## Contexte et objectif

L'interface actuelle ressemble à une application générique : beaucoup de cartes de même
poids, un tableau de bord chargé (six tuiles, trois graphiques, une barre de filtres), une
palette quasi monochrome. L'objectif est une interface plus aérée, qui n'affiche que les
informations importantes, avec plus de couleur mais sans couleurs vives.

La refonte est découpée en trois livraisons, chacune sur sa propre branche depuis
`origin/main` :

1. **Socle et accueil** (ce document).
2. Factures : tableau, filtres, panneaux règles et doublons, visionneuse, au style Brume.
3. Produits : tableau compact à cinq colonnes avec ligne dépliable, au style Brume.

Direction retenue parmi quatre maquettes : **Brume** (deux colonnes, bleu brume et abricot).

Principes appliqués : design engineering d'Emil Kowalski (`emil-design-eng`) et
recommandations Apple (`apple-design`).

## Décisions de l'utilisatrice

| Sujet | Décision |
| --- | --- |
| Découpage | Trois livraisons |
| Filtres sur l'accueil | Aucun |
| Gros chiffre | Total du dernier mois complet, mois en cours exclu |
| Évolution mensuelle | 12 mois au maximum, mois en cours inclus |
| Heatmap | Conservée, valeur absolue uniquement (bouton absolu / relatif retiré) |
| Infobulle de la heatmap | Date, fournisseur, montant et nombre de factures du jour, total du jour tous fournisseurs, part du jour dans le mois du fournisseur |
| Dernières factures | Les 3 dernières importées |
| Police | Instrument Sans |
| Libellés de navigation | En français |

## Section 1 — Socle visuel

### Couleurs

Les jetons de `static/app.css` sont remplacés par la palette Brume (thème clair unique,
conservé : l'outil se lit à côté des factures papier et des exports).

| Jeton | Rôle | Valeur |
| --- | --- | --- |
| `--plane` | fond de page | `#eff3f6` |
| `--surface` | cartes | `#ffffff` |
| `--ink` | texte principal | `#1b2830` |
| `--ink-secondary` | texte secondaire | `#3a4a54` |
| `--ink-muted` | légendes | `#64747e` |
| `--grid` | filets, grilles | `#e2e9ee` |
| `--series-1` | accent (liens, focus, barre du pic) | `#467a91` |
| `--series-1-soft` | barres, pastilles | `#b2cfdb` |
| `--apricot` | alertes de prix, erreurs d'import | `#a66c50` |
| `--uncertain` | champ à vérifier (orange pâle) | `#f5e5d2` |
| `--edited` | champ corrigé à la main (vert pâle) | `#dcebe1` |

Les noms de jetons existants sont conservés quand ils existent déjà, pour limiter les
changements dans le reste du CSS (livraisons 2 et 3).

**Heatmap.** Le dégradé vert → rouge est une demande produit (voir `CLAUDE.md`). Il est
conservé mais désaturé, avec une luminosité qui baisse strictement d'un palier à l'autre :
c'est ce qui le garde lisible en niveaux de gris et pour un lecteur daltonien. Les paliers
de `charts.HEAT_STOPS` sont ajustés en conséquence, et un test vérifie la décroissance de la
luminosité.

### Police

Instrument Sans (licence SIL Open Font License), fichiers `woff2` hébergés dans
`static/fonts/`, déclarés en `@font-face` avec `font-display: swap` et un repli
`system-ui, -apple-system, "Segoe UI", sans-serif`. La politique de sécurité de l'application
(`default-src 'self'`) bloque Google Fonts ; les fichiers viennent du paquet npm de la police.

### Typographie (Apple)

- Interlettrage selon la taille : `-0.02em` sur les gros chiffres, `-0.01em` sur les titres,
  `0` sur le texte courant, légèrement positif sur les petites étiquettes en capitales.
- Interligne inverse de la taille : `1.05` sur les gros chiffres, `1.2` sur les titres, `1.5`
  sur le texte.
- Tailles en `rem`, pour suivre le réglage de taille de texte du navigateur.
- Chiffres à largeur fixe (`font-variant-numeric: tabular-nums`) partout où des montants
  s'alignent.

### Navigation

Barre supérieure collante et translucide : fond blanc semi-transparent avec
`backdrop-filter: blur(20px) saturate(180%)`, le contenu défilant en dessous. Le filet sous
la barre n'apparaît que lorsque du contenu passe dessous (classe posée au défilement), au lieu
d'un filet permanent. Sélecteur en trois segments : « Tableau de bord », « Factures »,
« Produits », l'onglet actif sur fond blanc avec une ombre légère.

- `prefers-reduced-transparency: reduce` : fond opaque, sans flou.
- `prefers-contrast: more` : fond opaque et bordure nette.

### Mouvement et réactivité

- Boutons : retour dès l'appui (`:active`, `scale(0.97)`, 100 ms `ease-out`).
- Infobulle : fondu et léger agrandissement depuis la case survolée (`transform-origin` sur
  le point d'ancrage), 150 ms, courbe `cubic-bezier(0.23, 1, 0.32, 1)`. Les infobulles
  suivantes s'ouvrent sans délai ni animation.
- Survols réservés aux pointeurs fins : `@media (hover: hover) and (pointer: fine)`.
- Aucune animation sur une action déclenchée au clavier.
- `prefers-reduced-motion: reduce` : fondus courts uniquement, aucun déplacement.
- Seules `transform` et `opacity` sont animées ; jamais `transition: all`.

### Inchangé

Thème clair unique, règle globale `[hidden] { display: none !important }`, ressources servies
via `static_url()`, une seule couleur de bouton (le bleu est réservé aux liens et au focus),
aucun texte d'interface ne nomme le modèle (« l'automate »).

## Section 2 — Accueil

### Disposition

```
┌──────────────────────────────────────────────┬───────────────────────┐
│ Total facturé · septembre 2026               │ Dernier import        │
│ 1 288 000 KES  [+ 3 200 USD]                 │ 120 · 3 doublons · 1  │
│ 412 factures en septembre · 9 à vérifier     ├───────────────────────┤
│ ▁▃▂▅▄█▆▅▄▃▂░  (12 mois, le dernier en cours)  │ Alertes de prix (3)   │
├──────────────────────────────────────────────┴───────────────────────┤
│ Heatmap jour × fournisseur (valeur absolue, infobulle au survol)     │
├──────────────────────────────────────────────────────────────────────┤
│ 3 dernières factures importées                                       │
└──────────────────────────────────────────────────────────────────────┘
```

Sous 900 px de large, les deux colonnes s'empilent.

### Gros chiffre

- Période : le dernier mois civil complet par rapport à la date du jour du serveur. En
  janvier, c'est décembre de l'année précédente.
- Montant : somme de `total_amount` des factures sans erreur dont `invoice_date` tombe dans ce
  mois.
- Devises : le total affiché est celui de la **devise principale** du mois (celle qui a le
  plus de factures, égalité départagée par le montant). Chaque autre devise apparaît dans une
  pastille « + montant devise ». Aucun total ne mélange deux devises.
- Ligne secondaire : « N factures en {mois} » (même mois) et « M à vérifier » (compteur
  global, lien vers `/invoices?status=uncertain`).
- Mois sans facture : « Aucune facture en {mois} » à la place du montant.

### Évolution mensuelle

- Au plus 12 barres, du mois M-11 au mois en cours inclus. La série commence au premier mois
  de cette fenêtre qui a une facture ; ensuite chaque mois a sa place, et un mois sans facture
  laisse un emplacement vide plutôt que de rapprocher ses voisins.
- Devise principale de la période uniquement ; si d'autres devises existent, une note
  l'indique sous le graphique.
- Le mois en cours est dessiné plus clair, avec la mention « en cours », et garde sa place
  même sans facture.
- Seul le pic porte son montant (règle maison existante).

### Dernier import

- Le lot le plus récent (`batches`), via `db.batch_summary` : factures intégrées, doublons,
  erreurs, libellé (nom de l'archive), heure de fin, lien `/invoices?batch=<id>`.
- Lot en cours : barre de progression et temps restant, alimentés par le polling existant de
  `/api/batches/{id}`.
- Lot interrompu : statut « interrompu », via `_reconcile_batch`.
- Aucun lot : lien « Importer des factures ».

### Alertes de prix

- Calcul : `products.summarise(db.product_lines(slug, {}), DEFAULT_ALERT_THRESHOLD)`, en
  gardant les lignes en alerte, triées par `drift` décroissant, les 3 premières.
- Affichage : libellé du produit, fournisseur, « + N % ». Lien vers `/products`.
- Aucune alerte : « Aucune hausse au-delà de 25 % ».

### Heatmap

- Valeur absolue uniquement ; le bouton et les attributs `data-fill-rel` disparaissent.
- Limites inchangées : 12 fournisseurs, 45 derniers jours, avec la mention de ce qui est
  masqué.
- Infobulle, construite avec `textContent` :
  - date et fournisseur ;
  - montant du jour et nombre de factures, avec leurs numéros si 3 ou moins ;
  - total du jour, tous fournisseurs ;
  - part du jour dans le mois du fournisseur (« 18 % de son mois »).
- Données ajoutées par case : `invoice_count`, numéros de facture (via `GROUP_CONCAT` dans la
  requête jour × fournisseur), total du jour, total du mois du fournisseur. Calculés dans
  `charts.daily_heatmap`, transmis en attributs `data-*` échappés par Jinja.

### 3 dernières factures importées

- `ORDER BY created_at DESC LIMIT 3`.
- Colonnes : fournisseur, numéro, date, montant et devise, avec les surlignages « à vérifier »
  et « corrigé à la main ».
- Un clic sur la ligne ouvre l'original (`/invoices/{id}/file`) quand il existe.

### Retirés de l'accueil

Barre de filtres, graphique des principaux fournisseurs, TVA cumulée, nombre de fournisseurs,
bandeau multi-devises (remplacé par la pastille), tuile « En erreur » (les erreurs restent
dans « Dernier import »).

`charts.supplier_bars` et `db.dashboard_stats` restent dans le code tant qu'aucune autre page
ne s'en sert plus ; leur suppression éventuelle relève d'un nettoyage séparé.

### Côté code

| Fichier | Changement |
| --- | --- |
| `db.py` | `month_totals_by_currency(slug, year, month)`, `monthly_series(slug, months=12)`, `latest_batch(slug)`, `latest_invoices(slug, limit=3)`, requête jour × fournisseur enrichie |
| `dashboard.py` (nouveau) | Fonctions pures : dernier mois complet, fenêtre de 12 mois, devise principale, sélection des alertes |
| `charts.py` | `monthly_columns` gère le mois en cours ; `daily_heatmap` produit les données d'infobulle et n'a plus de valeur relative ; paliers désaturés |
| `app.py` | Route `/dashboard` simplifiée (plus de filtres), assemble les blocs |
| `templates/base.html` | Barre de navigation translucide, libellés français |
| `templates/dashboard.html` | Nouvelle disposition |
| `static/app.css` | Jetons Brume, typographie, navigation, accueil, mouvement |
| `static/app.js` | Infobulle de la heatmap, filet de la barre au défilement ; retrait de la bascule absolu / relatif |
| `static/fonts/` | Fichiers Instrument Sans |

Les pages Factures et Produits héritent des nouveaux jetons et de la navigation ; leur mise en
page propre change dans les livraisons 2 et 3.

## Section 3 — Cas limites, sécurité, tests, livraison

### Cas limites

- Factures sans date ou avec une date mal formée : ignorées par les calculs mensuels et la
  heatmap, comme aujourd'hui.
- Factures en erreur : exclues des montants.
- Mois en cours sans facture : barre vide à sa place, mention « en cours ».
- Alertes recalculées à chaque affichage. Le volume de référence (environ 1 200 factures) le
  permet ; un cache sera envisagé seulement si l'accueil ralentit.

### Sécurité

- Aucun texte issu d'une facture n'est inséré en HTML : infobulle construite par nœuds et
  `textContent`.
- Aucun script inline ; la politique de sécurité ne change pas ; les polices sont servies par
  l'application.
- Compatibilité Python 3.8 : pas de `X | None` ni de génériques `list[...]` dans les
  signatures de routes de `app.py`.

### Tests

Le dépôt n'a pas de suite de tests. Cette livraison ajoute :

- `requirements-dev.txt` avec `pytest`, séparé de `requirements.txt` pour ne pas alourdir
  l'installation des postes ;
- `tests/test_dashboard.py` : dernier mois complet (cas général, janvier), fenêtre de 12 mois
  avec le mois en cours, choix de la devise principale (égalité comprise), sélection des
  3 alertes ;
- `tests/test_charts.py` : données de l'infobulle de la heatmap, décroissance stricte de la
  luminosité des paliers, mois en cours dans `monthly_columns`.

Tests écrits avant le code (TDD). Vérification visuelle : application lancée avec des données
d'exemple, captures en largeur ordinateur et téléphone.

### Livraison

Une PR de `claude/refonte-brume-accueil` vers `main`, contenant cette spécification, le plan
d'implémentation et le code.

### Hors périmètre

- Mise en page des pages Factures et Produits (livraisons 2 et 3).
- Incompatibilité de Starlette récente avec `TemplateResponse` : branche séparée.
