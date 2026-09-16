# Plateforme d'extraction de factures

Application web qui extrait automatiquement les données des factures fournisseurs
(PDF, photos, imprimées ou manuscrites, français ou anglais) grâce à l'IA (Claude Sonnet 5),
et les présente dans deux onglets : un **Dashboard** de suivi et un tableau **Invoices**
consultable, corrigeable et exportable en Excel.

Chaque entreprise cliente dispose de son propre espace : sa propre URL, ses propres comptes,
sa propre base de données et ses propres fichiers. Aucune donnée n'est partagée entre clients.

## Démarrage rapide (poste local)

Double-clique sur le raccourci **« Extraction de factures »** (ou sur `Lancer.bat`).
Le navigateur s'ouvre sur http://127.0.0.1:8000 dès que le serveur est prêt.

Au tout premier lancement, la page te propose de créer ton compte. Ensuite, connexion
par e-mail + mot de passe.

Pour arrêter l'outil : ferme la fenêtre noire du terminal.

## Les deux onglets

**Dashboard** — total facturé, nombre de factures, TVA cumulée, nombre de fournisseurs,
factures à vérifier et en erreur. Deux graphiques : montant facturé par mois, et classement
des principaux fournisseurs. Filtrable par fournisseur et par période.

**Invoices** — le tableau de toutes les factures extraites, avec :

- **Surlignage orange pâle** sur les champs dont l'extraction n'est pas sûre : valeur
  illisible, déduite du contexte, ou étiquette ambiguë sur le document. La colonne
  « Remarques » explique le doute.
- **Surlignage vert pâle** sur les champs que tu as corrigés à la main.
- **Édition directe** : clique dans une cellule, modifie, appuie sur Entrée. Modifiables :
  fournisseur, numéro, date, montant, devise, TVA. Les montants acceptent le format français
  (`1 234,56`).
- **Filtres** : fournisseur, période, état (à vérifier / en erreur / sans erreur), recherche
  libre.
- **Consultation de l'original** : clique sur le nom du fichier pour afficher la facture
  d'origine (PDF ou photo) sans quitter la page.
- **Export Excel** : exporte exactement ce que les filtres affichent, avec le même code
  couleur et une feuille « Légende ».

## Comment Claude apprend de tes corrections

Chaque correction manuelle est enregistrée. Quand plusieurs corrections s'accumulent,
Claude les analyse et en déduit une **consigne courte et généralisable**, stockée par
fournisseur — par exemple : *« Pour ce fournisseur, ne pas utiliser le long numéro figurant
près du code-barres comme numéro de facture ; retenir la référence au format MAF-XXXXX. »*

Ces consignes sont automatiquement injectées dans les instructions d'extraction des imports
suivants. Le principe : on n'enregistre pas la valeur corrigée (qui ne servirait qu'une fois),
mais la **règle** derrière la correction (qui vaut pour toutes les factures à venir).

Le panneau « Ce que Claude a appris de vos corrections » sur l'onglet Invoices liste ces
règles, permet de les déclencher manuellement, et d'en supprimer une qui ne conviendrait pas.

## Import de factures

Bouton « Importer des factures » sur l'onglet Invoices. Accepte :

- des fichiers individuels : PDF, JPG, PNG, WEBP
- des **dossiers compressés `.zip`**, y compris avec des sous-dossiers (par mois, par
  fournisseur) et des archives imbriquées

L'import tourne en arrière-plan : la barre de progression suit l'avancement et tu peux
continuer à naviguer. Les factures sont traitées 8 en parallèle — compte environ 30 à 45
minutes et 10 à 12 € pour un lot de 1000 factures.

Les fichiers qui ne sont ni des PDF ni des images apparaissent quand même dans le tableau,
avec une erreur expliquant qu'ils ont été ignorés : rien ne disparaît silencieusement.

## Administration des espaces clients

```
python manage.py tenants                              # lister les espaces
python manage.py add-tenant acme --name "ACME SARL"   # créer un espace client
python manage.py add-user acme compta@acme.fr         # créer un compte
python manage.py reset-password acme compta@acme.fr   # changer un mot de passe
```

Un espace `acme` est servi sur `https://acme.<votre-domaine>`. En local, tout passe par
l'espace par défaut sur http://127.0.0.1:8000.

## Mise en production

Variables d'environnement à définir (dans `.env` ou dans l'hébergeur) :

| Variable | Rôle |
|---|---|
| `ANTHROPIC_API_KEY` | Clé API Anthropic (obligatoire) |
| `SESSION_SECRET` | Clé de signature des sessions. **À définir en production** ; la changer déconnecte tout le monde |
| `APP_DOMAIN` | Domaine de la plateforme, ex. `factures.example.com`. C'est lui qui distingue `acme.factures.example.com` (client ACME) du domaine nu |
| `DATA_DIR` | Emplacement des données (défaut : `./data`). **Le seul dossier à sauvegarder** |
| `MAX_CONCURRENT_EXTRACTIONS` | Factures traitées en parallèle (défaut : 8) |
| `AUTO_LEARN_THRESHOLD` | Corrections avant analyse automatique (défaut : 3) |

À prévoir également : servir en HTTPS derrière un reverse proxy, passer `https_only=True` sur
la session dans `app.py`, faire pointer un DNS joker `*.<domaine>` vers le serveur, et
sauvegarder `DATA_DIR` (il contient les bases SQLite et les factures originales).

## Notes

- Un fichier = une facture. Si un PDF contient plusieurs factures, seule la première est
  extraite et une remarque le signale.
- Les dates sont toujours normalisées au format AAAA-MM-JJ, les devises en code ISO
  (EUR, USD, KES...), et les montants en nombres décimaux.
- Si plusieurs devises coexistent, le Dashboard le signale : additionner des montants de
  devises différentes n'aurait pas de sens.
