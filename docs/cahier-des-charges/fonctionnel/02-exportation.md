# Exportation

Fait partie du [cahier des charges](../README.md) · état au 27 octobre 2026 (`main` + PR #4).

## Objectif

Sortir de l'application la liste des factures telle qu'on la regarde, pour la reprendre dans un tableur.

## Parcours

1. Sur la page Factures, l'utilisateur filtre et trie la liste.
2. Il clique sur « Exporter en Excel » : le fichier `factures_<espace>_<date>.xlsx` reprend exactement la liste filtrée et triée.
3. Dans le fichier, les cellules douteuses sont en orange et les cellules corrigées en vert, comme à l'écran.

## Exigences

Chaque exigence indique le test du dépôt qui la vérifie, ou « non couverte ».

- **EF-EXP-1** — L'application doit exporter en Excel la liste filtrée et triée, avec le code couleur de la vérification : orange pour un champ douteux, vert pour un champ corrigé.
  - *Test :* **non couverte**
- **EF-EXP-2** — L'export doit contenir, pour chaque facture, l'archive, le fichier, les six champs d'en-tête, les remarques et l'erreur éventuelle, avec une feuille « Legende » qui explique le code couleur.
  - *Test :* **non couverte**
- **EF-EXP-3** — L'export doit porter au plus 100 000 factures, chargées en une fois.
  - *Test :* **non couverte**

## Règles de gestion et cas limites

- L'export suit tous les filtres de la page (recherche, fournisseur, période, statut, import) et son tri.
- La première ligne est figée et porte un filtre automatique.
- Les factures en erreur sont exportées avec leur message d'erreur.

## Limites connues

- Seule la liste des factures s'exporte : ni les lignes d'articles, ni la page Produits, ni l'accueil.
- Les 100 000 factures au plus sont chargées en mémoire d'un seul tenant.
