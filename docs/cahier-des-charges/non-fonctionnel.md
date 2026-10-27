# Exigences non fonctionnelles

Fait partie du [cahier des charges](README.md) · état au 27 octobre 2026 (`main` + PR #4).

Ces exigences valent pour toute l'application. Chacune indique le test du dépôt qui la vérifie, ou « non couverte ».

## Performances et coûts (`PERF`)

- **ENF-PERF-1** — L'application doit traiter au plus 8 documents en parallèle (`MAX_CONCURRENT_EXTRACTIONS`), pour rester dans les limites de débit de l'API.
  - Mesure du 17 septembre 2026 sur 24 factures réelles :
    - environ 10 s par facture pour un traitement seul, dont 71 % passés dans l'appel à
      l'automate ;
    - 1,58 s par facture en lot, soit environ 31 min pour les 1 181 factures du jeu de
      référence.
  - Ces temps datent d'avant l'extraction des lignes de facture (27 septembre), qui a
    allongé les réponses de l'automate (voir [l'architecture](architecture.md), coût par facture). Ils sont à remesurer ; l'estimation du
    temps restant (`ESTIMATED_SECONDS_PER_INVOICE` = 10 s) repose encore sur eux.
  - *Test :* **non couverte**
- **ENF-PERF-2** — L'application doit refaire jusqu'à 6 tentatives d'un appel en cas de surcharge de l'API (erreurs 429 et 529) avant de déclarer l'extraction en échec.
  - *Test :* **non couverte**
- **ENF-PERF-3** — L'application doit placer les consignes système, règles apprises comprises, en cache d'API : elles sont identiques pour toutes les factures d'un import.
  - Mesure de septembre : environ 7 $ économisés sur un lot de 1 181 factures.
  - *Test :* **non couverte**
- **ENF-PERF-4** — L'application doit limiter le nombre de règles injectées à 60 (`MAX_RULES_IN_PROMPT`), et doit réduire les images à 2 000 pixels sur le grand côté.
  - *Test :* **non couverte**
- **ENF-PERF-5** — L'application ne doit pas décompresser en mémoire les documents d'une archive avant qu'un traitement les prenne en charge : chaque document est lu à ce moment-là.
  - Exception : une archive imbriquée dans une autre est lue entière en mémoire au dépliage, et l'archive envoyée est conservée entière, compressée, pendant l'import.
  - *Test :* **non couverte**
- **ENF-PERF-6** — L'apprentissage des règles, qui est un appel bloquant de plusieurs secondes, doit s'exécuter hors de la boucle d'événements du serveur, pour ne pas figer les autres requêtes.
  - *Test :* `tests/test_invoice_review.py::test_confirm_learns_off_the_event_loop`, `tests/test_invoice_review.py::test_correction_learns_off_the_event_loop`

## Stockage et quota (`STO`)

- **ENF-STO-1** — L'application doit mesurer l'espace occupé par un client sur le disque (originaux et fichiers SQLite, y compris `-wal` et `-shm`), et non en additionnant les tailles déclarées.
  - *Test :* **non couverte**
- **ENF-STO-2** — L'application doit refuser un import quand le quota est déjà atteint, et doit arrêter un import en cours au quota, en transformant chaque fichier refusé en ligne en erreur.
  - *Test :* **non couverte**
- **ENF-STO-3** — L'application ne doit pas recompresser les originaux : ils sont conservés à l'identique, pour garder leur valeur de copie fidèle.
  - Mesure de septembre : environ 1,1 Mo par facture et environ 2 Go par client et par an.
  - *Test :* **non couverte**
- **ENF-STO-4** — L'application doit refuser une requête d'import qui dépasse `MAX_UPLOAD_MB` (500 Mo par défaut).
  - *Test :* **non couverte**

## Sécurité (`SEC`)

- **ENF-SEC-1** — L'application ne doit jamais insérer un texte venu d'un document (fournisseur, remarques, libellés) comme du HTML : seulement comme du texte.
  - *Test :* `tests/test_home_route.py::test_home_escapes_supplier_names` (partielle : accueil seulement ; le script et les autres pages ne sont pas testés)
- **ENF-SEC-2** — L'application doit envoyer une politique de sécurité du contenu qui interdit tout script en ligne ou tiers (`script-src 'self'`).
  - *Test :* **non couverte**
- **ENF-SEC-3** — L'application doit dériver le nom de stockage d'un original de l'identifiant de la facture, ne doit accepter qu'une extension de la forme `^\.[a-z0-9]{1,8}$`, et doit vérifier que le chemin final reste dans le dossier du client.
  - *Test :* **non couverte**
- **ENF-SEC-4** — L'application doit revérifier ce confinement avant de servir un original ou une page rendue, et ne doit servir dans le navigateur que les PDF et les images (JPEG, PNG, WebP).
  - *Test :* **non couverte**
- **ENF-SEC-5** — L'application doit refuser une session dont l'espace client n'est pas celui de l'adresse demandée, ou dont le compte n'existe plus.
  - *Test :* **non couverte**
- **ENF-SEC-6** — L'application doit vider la session avant d'en ouvrir une nouvelle à la connexion.
  - *Test :* **non couverte**
- **ENF-SEC-7** — L'application doit bloquer pendant 5 minutes un couple adresse e-mail + adresse IP après 5 échecs de connexion.
  - *Test :* **non couverte**
- **ENF-SEC-8** — L'application doit stocker les mots de passe hachés avec scrypt.
  - *Test :* **non couverte**
- **ENF-SEC-9** — L'application doit marquer le cookie de session `Secure` dès que `APP_DOMAIN` est défini, et doit le garder en `SameSite=Lax`, qui tient lieu de protection CSRF.
  - *Test :* **non couverte**
- **ENF-SEC-10** — L'application doit autoriser l'affichage dans un cadre de la même origine seulement (`SAMEORIGIN`, `frame-ancestors 'self'`), jamais `DENY` ni `'none'`.
  - *Test :* **non couverte**
- **ENF-SEC-11** — L'application doit interdire la mise en cache des réponses sous `/invoices`, `/api` et `/dashboard`, et des images de pages.
  - *Test :* `tests/test_pages_route.py::test_pdf_page_is_rendered_as_png` (partielle : images de pages seulement)
- **ENF-SEC-12** — L'application doit refuser la modification de tout champ hors des six champs d'en-tête modifiables (`db.EDITABLE_FIELDS`).
  - *Test :* `tests/test_invoice_review.py::test_confirm_rejects_a_field_that_is_not_doubtful` (partielle : ce test passerait même sans le contrôle `EDITABLE_FIELDS`, car le champ refusé n'est pas douteux ; la route de correction n'est pas testée)

## Isolation des clients (`ISO`)

- **ENF-ISO-1** — Chaque espace client doit avoir sa propre base SQLite et son propre dossier de fichiers, sans table partagée ni colonne d'espace.
  - *Test :* **non couverte**
- **ENF-ISO-2** — L'application doit déterminer l'espace client à partir de l'adresse demandée (sous-domaine de `APP_DOMAIN`), et un sous-domaine inconnu doit recevoir une erreur 404 au lieu de créer un espace.
  - *Test :* **non couverte**
- **ENF-ISO-3** — L'application doit appliquer chaque évolution de schéma à toutes les bases existantes par des migrations additives, à la première ouverture de chaque base.
  - *Test :* `tests/test_migrations.py::test_old_database_gets_new_columns_and_log`, `tests/test_migrations.py::test_duplicates_are_copied_only_once`

## Compatibilité (`COMP`)

- **ENF-COMP-1** — L'application doit fonctionner sous Python 3.8 (version installée sur le poste de développement) : pas de syntaxe PEP 585 ou 604 évaluée à l'exécution, notamment dans les signatures des routes.
  - *Test :* **non couverte**
- **ENF-COMP-2** — L'application doit s'installer et se lancer sur un poste Windows par `Installer.bat` et `Lancer.bat`, sans ligne de commande.
  - *Test :* **non couverte**
- **ENF-COMP-3** — L'application doit fonctionner dans les navigateurs récents sur ordinateur et sur téléphone, sans étape de construction du front (une feuille de style, un script).
  - *Test :* **non couverte**

## Conventions d'interface (`UI`)

- **ENF-UI-1** — L'interface ne doit jamais nommer le modèle : elle doit dire « l'automate ».
  - *Test :* **non couverte**
- **ENF-UI-2** — Tous les boutons doivent partager une même couleur ; le bleu doit être réservé aux liens et au focus.
  - *Test :* **non couverte**
- **ENF-UI-3** — L'interface doit respecter le réglage « réduire les animations » : les mouvements deviennent instantanés, et une action au clavier ne doit jamais être animée.
  - *Test :* **non couverte**
- **ENF-UI-4** — La couleur ne doit jamais être le seul moyen de lire une information : chaque case de la carte de chaleur porte aussi sa valeur en texte, et sa rampe de couleurs doit décroître en luminosité.
  - *Test :* `tests/test_charts.py::test_heat_stops_lightness_strictly_decreases`, `tests/test_charts.py::test_heatmap_tooltip_data`
- **ENF-UI-5** — L'application doit référencer la feuille de style et le script avec un numéro de version (`static_url`), pour qu'une mise à jour ne laisse pas l'ancien script en cache.
  - *Test :* **non couverte**
