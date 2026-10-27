# The Bill Please — cahier des charges

Référence de l'existant · état au 27 octobre 2026

## Sommaire

| Document | Contenu |
|---|---|
| [Importation](fonctionnel/01-importation.md) | Dépôt des fichiers, doublons, progression, bilan, et ce que lit l'automate |
| [Exportation](fonctionnel/02-exportation.md) | Export Excel de la liste des factures |
| [Dashboard d'accueil](fonctionnel/03-accueil.md) | Total du mois, évolution, carte par jour, dernier import |
| [Dashboard produits](fonctionnel/04-produits.md) | Filtres, prix par produit et par fournisseur, alertes, historique |
| [Tableau des factures](fonctionnel/05-tableau-factures.md) | Liste, filtres, tri, visionneuse, téléphone |
| [Vérification des valeurs à vérifier](fonctionnel/06-verification.md) | Zones douteuses, correction, confirmation, validation, règles apprises |
| [Administration](fonctionnel/07-administration.md) | Espaces clients, comptes, quotas en ligne de commande |
| [Exigences non fonctionnelles](non-fonctionnel.md) | Performances, stockage, sécurité, isolation, compatibilité, interface |
| [Architecture, coût et limites](architecture.md) | Modules, parcours d'une facture, données, API, coût par facture, limites techniques |

## Objet et périmètre

Ce document décrit ce que fait The Bill Please, ce qu'il doit garantir, et comment c'est construit.
Il s'adresse aux personnes qui développent l'application.

**État décrit :** la branche `main` (commit `23d0c3e`), plus la PR #4 « Refonte Brume : page
Factures » (commit `5a2ec93`). La PR #4 n'est pas encore fusionnée ; ce document est à fusionner
après elle.

**Lien avec `CLAUDE.md`.** `CLAUDE.md` est le guide de développement : il explique *pourquoi* le
code est écrit ainsi et ce qu'il ne faut pas casser. Ce document énonce *ce que* l'application doit
faire, sous forme d'exigences numérotées et vérifiables, et renvoie à `CLAUDE.md` pour le détail.
En cas de désaccord entre les deux, c'est le code qui fait foi, et l'un des deux documents est à
corriger.

**Documents de septembre.** Les trois PDF de `docs/` restent des documents datés. Voici ce qui a
changé depuis :

| Sujet | Septembre 2026 (PDF) | Aujourd'hui |
|---|---|---|
| Doublons | table `duplicates`, panneau « Doublons ignorés » sur la page Invoices | journal `import_log` en base avec un code raison ; aucun panneau ni liste ; les doublons sont comptés dans le bilan d'import, la carte « Dernier import » de l'accueil et `manage.py storage` |
| Réponse de l'automate | `max_tokens` 2 048 | 8 192 (les lignes de facture d'une facture de 40 lignes tronquaient la réponse) |
| Contenu extrait | champs d'en-tête, champs douteux, remarques | en plus : lignes de facture, zone de chaque champ douteux sur la page |
| Vérification | tableau éditable, visionneuse du document en fenêtre | liste / détail, visionneuse zoomable qui entoure les zones douteuses, confirmation et validation |
| Apprentissage | à partir des corrections | à partir des corrections et des confirmations |
| Accueil | tableau de bord avec filtres | accueil sans filtre : dernier mois complet, 12 mois, heatmap, alertes de prix, dernières factures |
| Tests | une suite de sécurité est mentionnée | elle n'est pas dans le dépôt (voir « Lire la vérification » ci-dessous) |

## Acteurs

- **Utilisateur d'un espace client.**
  - Il a un compte (adresse e-mail et mot de passe) dans un espace client.
  - Il importe, vérifie, corrige et exporte les factures de cet espace, et uniquement de
    celui-là.
  - Tous les comptes d'un espace ont les mêmes droits : il n'y a pas de rôles.
- **Administrateur de la plateforme.**
  - Il agit en ligne de commande sur le serveur, avec `manage.py`.
  - Il crée les espaces clients et les comptes, change les mots de passe, consulte l'espace
    occupé et fixe les quotas.
  - Il n'a pas d'interface web.
- **Premier utilisateur d'un espace vide.** Tant qu'un espace n'a aucun compte, la page
  `/setup` permet d'y créer le premier.

## Lire la vérification

Chaque exigence porte une ligne « Test » : le test du dépôt qui la vérifie (avec « partielle » et ce qui manque, quand il n'en couvre qu'une part), ou **non couverte**. Les tests cités sont ceux de la branche de la PR #4 (75 tests, `pytest -q`).

Trois remarques pour lire les lignes « Test » :

- **Sécurité.** `CLAUDE.md` et la note de septembre citent une suite de tests de sécurité (cloisonnement entre clients, sessions, service des fichiers, imports). Elle n'est pas dans le dépôt : les exigences `ENF-SEC` qu'elle couvrait sont marquées non couvertes, ce qui veut dire *non vérifiées par un test présent*, pas *non respectées*.
- **Navigateur.** Le comportement de la page Factures (sélection, visionneuse, zones, téléphone) a été vérifié par des contrôles Playwright pendant la PR #4. Ces scripts ne sont pas dans le dépôt, donc ils ne comptent pas ici.
- **Automate.** Ce que l'automate lit sur un document (`EF-IMP-12` à `EF-IMP-15`) dépend du modèle et des consignes ; aucun test du dépôt ne le vérifie sans appel réel à l'API.
