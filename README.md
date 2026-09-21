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
- **Vérification contre l'original** : clique sur le nom du fichier pour afficher la facture
  d'origine (PDF ou photo) avec, juste à côté, les champs lus par l'automate. Tu les corriges
  en regardant le document ; les boutons « Précédente / Suivante » enchaînent les factures
  du tableau sans refermer la fenêtre.
- **Export Excel** : exporte exactement ce que les filtres affichent, avec le même code
  couleur et une feuille « Légende ».

## Comment l'automate apprend de tes corrections

Chaque correction manuelle est enregistrée. Quand plusieurs corrections s'accumulent,
l'automate les analyse et en déduit une **consigne courte et généralisable**, stockée par
fournisseur — par exemple : *« Pour ce fournisseur, ne pas utiliser le long numéro figurant
près du code-barres comme numéro de facture ; retenir la référence au format MAF-XXXXX. »*

Ces consignes sont automatiquement injectées dans les instructions d'extraction des imports
suivants. Le principe : on n'enregistre pas la valeur corrigée (qui ne servirait qu'une fois),
mais la **règle** derrière la correction (qui vaut pour toutes les factures à venir).

Le panneau « Ce que l'automate a appris de vos corrections » sur l'onglet Invoices liste ces
règles, permet de les déclencher manuellement, et d'en supprimer une qui ne conviendrait pas.

## Import de factures

Bouton « Importer des factures » sur l'onglet Invoices. Accepte :

- des fichiers individuels : PDF, JPG, PNG, WEBP
- des **dossiers compressés `.zip`**, y compris avec des sous-dossiers (par mois, par
  fournisseur) et des archives imbriquées

L'import tourne en arrière-plan : la barre de progression suit l'avancement, un compte à
rebours indique le temps restant estimé, et tu peux continuer à naviguer. La première
estimation repose sur des temps mesurés (~10 s par facture) ; elle s'ajuste ensuite au débit
réellement observé pendant l'import. Si le serveur redémarre en cours d'import, la page
l'indique : redépose les mêmes fichiers, les factures déjà intégrées seront ignorées. Les factures sont traitées 8 en parallèle — compte environ 30 à 45
minutes et 10 à 12 € pour un lot de 1000 factures.

À la fin de l'import, une fenêtre **Bilan de l'import** récapitule le lot : factures intégrées
avec succès (dont celles à vérifier), doublons ignorés, factures non intégrées par cause
(échec d'extraction, fichier non exploitable, quota atteint), avec la liste des fichiers
concernés et des liens pour filtrer le tableau sur cet import. Si tu as quitté la page pendant
l'import, le bilan s'affiche à ta prochaine visite, jusqu'à ce que tu le fermes.

Les fichiers qui ne sont ni des PDF ni des images apparaissent quand même dans le tableau,
avec une erreur expliquant qu'ils ont été ignorés : rien ne disparaît silencieusement.

### Doublons

Chaque document reçoit une empreinte numérique à l'import. Un document **strictement
identique** à une facture déjà importée — dans un lot précédent ou dans le même lot — est
ignoré : il n'est ni stocké, ni envoyé à l'extraction (donc pas facturé), ni compté deux fois
dans les totaux du Dashboard. Le panneau « Doublons ignorés à l'import » de l'onglet Invoices
liste ces documents et renvoie vers la facture d'origine.

Sur tes archives de référence : 39 doublons sur 1181 fichiers, soit 100 Mo évités — dont
plusieurs factures présentes à la fois dans deux archives mensuelles.

Seule exception : si la première importation d'un document avait **échoué** (par exemple une
surcharge de l'API), le réimporter relance l'extraction et remplace la ligne en erreur.

### Espace de stockage

L'espace occupé par l'espace client (factures originales + base de données) est affiché en
haut de l'onglet Invoices. Si un quota est défini, une jauge l'accompagne : orange au-delà de
80 %, rouge au-delà de 95 %. Une fois le quota atteint, les nouveaux imports sont refusés.

## Administration des espaces clients

```
python manage.py tenants                              # lister les espaces
python manage.py add-tenant acme --name "ACME SARL"   # créer un espace client
python manage.py add-user acme compta@acme.fr         # créer un compte
python manage.py reset-password acme compta@acme.fr   # changer un mot de passe
python manage.py storage acme                         # détail de l'espace occupé
python manage.py set-quota acme 5000                  # quota en Mo (0 = illimité)
```

`tenants` affiche l'espace occupé et le quota de chaque client. `storage` détaille la part
des factures originales et de la base, la taille moyenne par facture, le poids des fichiers
de plus de 5 Mo, l'espace évité par le dédoublonnage et les plus gros documents.

Ordre de grandeur mesuré sur des factures réelles : ~1,1 Mo par facture, soit environ 2 Go par
an pour un client traitant ~170 factures par mois.

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
| `DEFAULT_STORAGE_QUOTA_MB` | Quota appliqué aux clients sans quota propre, en Mo (défaut : 0 = illimité) |

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
