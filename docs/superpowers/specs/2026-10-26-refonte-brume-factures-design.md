# Refonte « Brume » — livraison 2 : page Factures

Date : 2026-10-26
Statut : en relecture
Branche : `claude/refonte-brume-factures` (créée depuis `origin/main`, qui contient la livraison 1)

## Contexte et objectif

La page Factures empile aujourd'hui l'import, une barre de filtres pleine largeur, le panneau
des règles apprises, le panneau des doublons, un tableau à huit colonnes éditables et une
visionneuse en fenêtre. L'objectif est une page de **vérification rapide** : une liste courte,
le document et ses champs côte à côte, et les zones douteuses montrées directement sur le
document.

Direction retenue parmi quatre maquettes : **« Liste et détail côte à côte »** (maquette 3),
dans le style Brume de la livraison 1. Principes appliqués : `emil-design-eng` et
`apple-design`.

## Décisions de l'utilisatrice

| Sujet | Décision |
| --- | --- |
| Structure | Liste à gauche, détail de la facture sélectionnée à droite |
| Filtres du tableau | Fournisseur, période, état (Toutes / À vérifier / En erreur), recherche |
| Tri | Par date ou par montant, dans les deux sens |
| Zones douteuses | Cadres orange sur le document, positions renvoyées par l'automate (option 1) |
| Test de précision des cadres | Pas pour l'instant |
| Document | Navigable : zoom, déplacement, pages — pas une image figée |
| Validation | « Confirmer » par champ douteux et « Valider la facture » |
| Apprentissage | Corrections **et** confirmations alimentent les règles du fournisseur ; les confirmations comptent pour le seuil d'analyse |
| Doublons | Plus aucun affichage dans l'application ; seul le message d'erreur du bilan d'import les mentionne |
| Journal | Journal d'import en base, avec la raison (`DUPLICATE` ou autre) ; l'ancien journal des doublons y est repris |
| Factures en erreur | Restent dans l'onglet « En erreur » **et** sont écrites dans le journal |

## Section 1 — Structure de la page

### En-tête

« Factures », puis « N factures · M à vérifier · K en erreur » (les deux derniers sont des
liens vers l'onglet correspondant). À droite : « Règles apprises · n », « Exporter en Excel »,
« Importer des factures ».

### Import

« Importer des factures » ouvre un panneau (feuille ancrée sous le bouton, qui se referme par
le même chemin) : zone de dépôt, liste des fichiers, lancement, progression et temps restant,
avec la logique d'import actuelle (`app.js`, polling de `/api/batches/{id}`). La jauge de
stockage s'y affiche. Le dépôt de fichiers reste possible sur toute la page.

### Barre d'outils

- Sélecteur d'état : « Toutes · n », « À vérifier · n », « En erreur · n » (paramètre
  `status`, déjà géré par `db._filter_clause`).
- Recherche (paramètre `search`).
- « Fournisseur » : liste des fournisseurs (paramètre `supplier`).
- « Période » : du / au (paramètres `date_from`, `date_to`).
- « Trier » : date récente d'abord (par défaut), date ancienne d'abord, montant décroissant,
  montant croissant (paramètre `sort`).

Tous les paramètres restent dans l'adresse ; l'export Excel les reprend, tri compris.

### Liste (gauche)

Une ligne par facture : pastille d'état (neutre, à vérifier, corrigée, erreur), fournisseur
(ou nom du fichier si l'extraction a échoué), date, montant et devise. Pagination par 100. La
ligne sélectionnée est sur fond teinté. Flèches haut / bas du clavier pour changer de
facture, sans animation.

### Détail (droite)

- **En-tête** : « Fournisseur · numéro », fichier et archive, flèches précédente / suivante,
  « Ouvrir l'original » (nouvel onglet).
- **Visionneuse** (section 2).
- **Champs** : les six champs modifiables (`EDITABLE_FIELDS`), surlignés comme aujourd'hui
  (orange pâle : à vérifier ; vert pâle : corrigé). Chaque champ douteux porte un bouton
  « Confirmer ».
- **Explication** : `extraction_notes`, et l'erreur s'il y en a une.
- **« Valider la facture »** : visible si la facture a au moins un champ douteux et pas
  d'erreur.

La facture sélectionnée est dans l'adresse (`?id=`), donc conservée au rechargement. Les
enregistrements restent liés à la facture sur laquelle la saisie a commencé (règle existante
de la visionneuse).

### Règles apprises

« Règles apprises · n » ouvre un panneau latéral avec le contenu actuel : liste des règles,
« Oublier », corrections et confirmations en attente, « Analyser maintenant ».

### Retirés

Panneau des doublons, barre de filtres pleine largeur, fenêtre `#docModal` (remplacée par le
détail), colonnes TVA / remarques / document dans la liste (présentes dans le détail).

### Téléphone (≤ 900 px)

La liste prend toute la largeur ; toucher une facture ouvre le détail en plein écran, avec un
bouton retour. La barre d'outils passe sur deux lignes.

## Section 2 — Données et comportements

### Cadres des champs douteux

- `extraction.INVOICE_SCHEMA` gagne `uncertain_regions` : tableau d'objets
  `{"field", "page", "x", "y", "width", "height"}`. `field` est l'un des
  `EXTRACTED_FIELDS` ; `page` commence à 1 ; les quatre autres valeurs sont des proportions
  de la page (0 à 1, origine en haut à gauche).
- `SYSTEM_PROMPT` demande un cadre pour chaque champ de `uncertain_fields`, autour de
  l'endroit où la valeur a été lue, et un tableau vide sinon.
- Nettoyage côté serveur (`extraction.clean_regions`) avant enregistrement : champ hors de
  `uncertain_fields` écarté ; page hors de `1..page_count` écartée ; valeurs ramenées dans
  `[0, 1]` ; cadre de largeur ou hauteur nulle écarté.
- Stockage : nouvelle colonne `invoices.uncertain_regions TEXT NOT NULL DEFAULT '[]'`,
  ajoutée aux bases existantes par `MIGRATIONS`.
- Quand un champ est confirmé ou corrigé, son cadre disparaît avec son doute.
- Coût : quelques dizaines de jetons de sortie en plus par facture douteuse.

### Pages de la visionneuse

- Nouvelle route `GET /invoices/{id}/pages/{n}.png` :
  - PDF : rendu de la page `n` avec PyMuPDF à 200 dpi, renvoyé en PNG ;
  - photo (JPG, PNG, WEBP) : seule la page 1 existe, renvoyée telle quelle avec son type.
- Mêmes protections que `/invoices/{id}/file` : session requise, chemin résolu dans le
  dossier du client avec contrôle d'appartenance, types de `VIEWABLE_TYPES` uniquement,
  `n` entier entre 1 et le nombre de pages (sinon 404), `Cache-Control: no-store, private`.
- `GET /api/invoices/{id}` est enrichi de `uncertain_regions`, `page_count` (nombre réel de
  pages du fichier conservé, 1 pour une photo, 0 sans fichier) et `extraction_notes`.

### Visionneuse (JavaScript maison, sans bibliothèque)

- Une page à la fois, image dans un conteneur avec `overflow: hidden`.
- Zoom de 50 % à 400 % : boutons « − » / « + » / « Ajuster », Ctrl + molette, pincement.
  Le zoom se fait autour du pointeur.
- Déplacement en faisant glisser (Pointer Events avec `setPointerCapture`, suivi 1:1, en
  respectant le point de prise), avec une résistance progressive au-delà des bords.
- Pages précédente / suivante, « page 2 / 3 ».
- Cadres orange en surimpression, positionnés en pourcentages de l'image : ils suivent le
  zoom et le déplacement sans recalcul.
- « Zone douteuse suivante » : change de page si besoin, puis centre et zoome sur le cadre
  (ressort critique, sans rebond, environ 0,35 s ; interruptible). Survoler ou mettre le
  focus sur un champ douteux met en évidence son cadre.
- Seules `transform` et `opacity` sont animées. Avec `prefers-reduced-motion: reduce`, le
  centrage est instantané.
- Sans fichier conservé : « Document original non conservé ». Sans cadre pour un champ
  douteux : le champ reste surligné, rien n'est dessiné.

### Confirmer et valider

- `POST /api/invoices/{id}/confirm` avec `{"field": …}` : le champ doit être dans
  `EDITABLE_FIELDS` et dans `uncertain_fields` (sinon 400). Il est retiré de
  `uncertain_fields` (pas ajouté à `edited_fields`), son cadre est retiré, et une ligne
  `corrections` est écrite avec `kind = 'confirmation'` et l'ancienne valeur égale à la
  nouvelle.
- `POST /api/invoices/{id}/validate` : confirme tous les champs douteux restants. Refusé
  (400) si la facture est en erreur.
- Une correction (`PATCH`, chemin actuel) écrit `kind = 'correction'`.
- Après une confirmation ou une validation, même déclenchement automatique de l'analyse que
  pour une correction (`AUTO_LEARN_THRESHOLD`, confirmations comprises).
- Réponse : l'état à jour (`uncertain_fields`, `uncertain_regions`, `pending_corrections`,
  `learned`), pour mettre à jour la liste et le détail sans recharger.

### Règles apprises

- Nouvelle colonne `corrections.kind TEXT NOT NULL DEFAULT 'correction'` (`MIGRATIONS`).
- `learning._format_corrections` écrit une confirmation sous la forme
  « champ X : valeur "v" signalée douteuse, confirmée exacte ». `RULE_SYSTEM_PROMPT` précise
  qu'une confirmation indique un doute inutile, à éviter pour ce fournisseur.

### Tri

`db.list_invoices(slug, filters, limit, offset, sort="date_desc")`, liste blanche :

| `sort` | Ordre SQL |
| --- | --- |
| `date_desc` (défaut) | `invoice_date IS NULL, invoice_date DESC, created_at DESC` |
| `date_asc` | `invoice_date IS NULL, invoice_date ASC, created_at ASC` |
| `amount_desc` | `total_amount IS NULL, total_amount DESC, created_at DESC` |
| `amount_asc` | `total_amount IS NULL, total_amount ASC, created_at ASC` |

Toute autre valeur retombe sur `date_desc`.

### Journal d'import

- Nouvelle table `import_log` : `id`, `batch_id`, `archive`, `filename`, `reason`
  (`DUPLICATE`, `UNSUPPORTED`, `EXTRACTION`, `QUOTA`, `OTHER`), `message`, `duplicate_of`,
  `invoice_id`, `file_size`, `created_at`, avec un index sur `batch_id`.
- À la création de la table sur une base existante, les lignes de `duplicates` y sont
  recopiées avec `reason = 'DUPLICATE'`. La table `duplicates` reste (migrations additives)
  mais n'est plus écrite.
- `pipeline._process_one` : un doublon écrit une ligne `DUPLICATE` à la place de
  `db.record_duplicate`. Un fichier refusé ou en échec d'extraction écrit sa ligne `invoices`
  en erreur, comme aujourd'hui, **et** une ligne `import_log`, dont la raison vient de
  `db.error_kind` (`quota` → `QUOTA`, `unsupported` → `UNSUPPORTED`, `extraction` →
  `EXTRACTION`, sinon `OTHER`).
- `db.batch_summary` compte les doublons et en donne les exemples depuis `import_log`.
- Bilan d'import (`app.js`) : un message d'erreur liste les fichiers non intégrés avec leur
  raison, doublons compris (« déjà importé, identique à … »). Le lien « Voir les doublons »,
  l'ancre `#doublons`, `openDuplicates` et la gestion `data-summary-anchor` correspondante
  sont retirés.
- `db.list_duplicates` et `db.duplicate_summary` ne sont plus appelés par la page ;
  `manage.py storage` continue d'afficher l'espace évité, calculé depuis `import_log`.

### Côté code

| Fichier | Changement |
| --- | --- |
| `extraction.py` | `uncertain_regions` dans le schéma et le prompt, `clean_regions`, champ dans `InvoiceResult` |
| `db.py` | Colonnes `invoices.uncertain_regions`, `corrections.kind` ; table `import_log` et reprise des doublons ; `confirm_fields`, `log_import_event`, tri de `list_invoices`, `batch_summary` sur le journal |
| `pipeline.py` | Écriture du journal, enregistrement des cadres |
| `learning.py` | Format des confirmations, consigne du prompt |
| `app.py` | Routes `confirm`, `validate`, `pages/{n}.png` ; `GET /api/invoices/{id}` enrichi ; page Factures sans doublons, avec tri |
| `templates/invoices.html` | Nouvelle structure liste / détail |
| `static/app.js` | Liste et détail, visionneuse, confirmation et validation, bilan d'import sans lien vers les doublons ; retrait de `#docModal` |
| `static/app.css` | Styles de la page, de la visionneuse et du panneau latéral |
| `manage.py` | `storage` lit l'espace évité dans `import_log` |
| `CLAUDE.md` | Sections doublons, bilan d'import, visionneuse et apprentissage mises à jour |

## Section 3 — Cas limites, sécurité, tests, livraison

### Cas limites

- Facture sans document conservé : visionneuse vide avec message ; champs modifiables.
- PDF de plus de 5 pages : toutes les pages sont consultables ; les cadres ne peuvent viser que
  les 5 premières (`MAX_PAGES_PER_INVOICE`).
- Factures importées avant cette livraison : pas de cadres ; tout le reste fonctionne.
- Facture en erreur : ni « Confirmer » ni « Valider ».
- Tri : les factures sans date ou sans montant viennent en fin de liste.
- Liste vide (filtres trop restrictifs) : message et lien « Réinitialiser les filtres » ;
  aucun détail affiché.
- `?id=` qui ne correspond à aucune facture de la page : la première facture est
  sélectionnée.

### Sécurité

- Route des pages : contrôle d'appartenance au dossier du client, numéro de page validé,
  types limités, `no-store`.
- Cadres : nombres validés côté serveur, appliqués en styles calculés par le JavaScript ;
  aucun texte de facture n'est inséré en HTML (`textContent` partout).
- `confirm` et `validate` : champs limités à `EDITABLE_FIELDS`, session requise, cookie
  `same_site="lax"` inchangé.
- Aucun script inline, politique de sécurité inchangée, aucune bibliothèque externe.
- Compatibilité Python 3.8 : `typing.List` / `typing.Optional` dans les signatures de routes.

### Tests (écrits avant le code)

- `tests/test_migrations.py` : une base créée avec l'ancien schéma reçoit les nouvelles
  colonnes et la table `import_log` ; les doublons existants y sont repris une seule fois.
- `tests/test_regions.py` : `clean_regions` (champ non douteux, page hors limites, valeurs
  hors de `[0, 1]`, taille nulle).
- `tests/test_invoice_review.py` : `confirm` (doute et cadre retirés, confirmation écrite,
  400 sur un champ non douteux ou non modifiable), `validate` (tous les doutes retirés, 400 sur
  une facture en erreur), seuil d'analyse atteint par des confirmations.
- `tests/test_invoice_list.py` : les quatre tris et la valeur inconnue ; la page ne contient
  plus le panneau des doublons.
- `tests/test_pages_route.py` : page PDF rendue en PNG, page hors limites en 404, facture d'un
  autre espace ou sans fichier en 404.
- `tests/test_import_log.py` : un doublon et un format non pris en charge écrivent leur ligne ;
  `batch_summary` compte les doublons depuis le journal.
- `tests/test_learning.py` : une confirmation est formatée comme telle dans le prompt.
- Vérification visuelle avec des données d'exemple contenant des cadres : ordinateur et
  téléphone, survol, zoom, zone douteuse suivante.

### Livraison

Une PR de `claude/refonte-brume-factures` vers `main`, avec cette spécification, le plan et le
code, et des captures de la page.

### Hors périmètre

- Page Produits (livraison 3).
- Réextraction des anciennes factures pour leur ajouter des cadres.
- Test de précision des cadres sur de vraies factures (reporté par l'utilisatrice).
- Correctif de compatibilité de Starlette avec `TemplateResponse`.
- Connexion sautée en local : livrée séparément (PR #3).
