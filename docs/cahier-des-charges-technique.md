# The Bill Please — cahier des charges technique

Référence de l'existant · état au 27 octobre 2026

## 1. Objet et périmètre

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
| Doublons | table `duplicates`, panneau « Doublons ignorés » sur la page Invoices | journal `import_log` en base avec un code raison ; aucun panneau, seul le bilan d'import les signale |
| Réponse de l'automate | `max_tokens` 2 048 | 8 192 (les lignes de facture d'une facture de 40 lignes tronquaient la réponse) |
| Contenu extrait | champs d'en-tête, champs douteux, remarques | en plus : lignes de facture, zone de chaque champ douteux sur la page |
| Vérification | tableau éditable, visionneuse du document en fenêtre | liste / détail, visionneuse zoomable qui entoure les zones douteuses, confirmation et validation |
| Apprentissage | à partir des corrections | à partir des corrections et des confirmations |
| Accueil | tableau de bord avec filtres | accueil sans filtre : dernier mois complet, 12 mois, heatmap, alertes de prix, dernières factures |
| Tests | une suite de sécurité est mentionnée | elle n'est pas dans le dépôt (voir section 8) |

## 2. Acteurs

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

## 3. Exigences fonctionnelles

Chaque exigence est numérotée `EF-<domaine>-<n>`. La section 8 indique le test qui la vérifie.

### 3.1 Import (`IMP`)

- **EF-IMP-1** — L'application doit accepter en import des fichiers PDF, JPEG, PNG et WebP, ainsi que des archives `.zip` qui en contiennent.
  - Une archive peut en contenir d'autres, jusqu'à 3 niveaux d'imbrication.
- **EF-IMP-2** — L'application doit ignorer sans erreur les fichiers système des archives (`__MACOSX/`, fichiers cachés, `Thumbs.db`), et doit signaler comme erreur tout autre fichier qui n'est ni un document ni une archive.
- **EF-IMP-3** — L'application doit répondre à un import sans attendre l'extraction : le traitement se poursuit en arrière-plan et la page affiche la progression.
- **EF-IMP-4** — L'application doit afficher pendant un import le nombre de documents traités et une estimation du temps restant.
  - L'estimation part d'un temps mesuré par facture, puis suit le rythme observé une fois
    qu'une série complète de traitements est terminée.
- **EF-IMP-5** — L'application doit refuser un second import dans un espace qui a déjà un import en cours.
- **EF-IMP-6** — L'application doit reconnaître une copie exacte d'un document déjà importé (même empreinte SHA-256), y compris au sein du même import, et ne doit ni la stocker, ni l'envoyer à l'automate, ni la compter dans les totaux.
- **EF-IMP-7** — L'application doit permettre de relancer un document dont l'extraction a échoué en le réimportant, sauf si l'utilisateur a modifié cette ligne à la main.
- **EF-IMP-8** — L'application doit inscrire dans le journal `import_log` chaque fichier d'un import qui n'est pas devenu une facture valide, avec un code raison : `DUPLICATE`, `UNSUPPORTED`, `EXTRACTION`, `QUOTA` ou `OTHER`.
- **EF-IMP-9** — L'application doit afficher à la fin d'un import un bilan : intégrées, déjà importées, en erreur par type d'erreur, non traitées.
  - Le bilan doit rester proposé tant que l'utilisateur ne l'a pas fermé, même s'il a quitté
    la page entre-temps.
- **EF-IMP-10** — L'application doit détecter un import interrompu par un redémarrage du serveur et le signaler comme tel ; un nouvel import des mêmes fichiers doit reprendre là où il s'est arrêté, grâce à la détection des doublons.
- **EF-IMP-11** — L'application doit conserver l'original de chaque document importé et doit le rendre consultable depuis la facture.

### 3.2 Extraction (`EXT`)

- **EF-EXT-1** — L'application doit extraire de chaque document le fournisseur, le numéro de facture, la date, le montant total, la devise et le montant de TVA.
- **EF-EXT-2** — L'application doit rendre les dates au format `AAAA-MM-JJ`, les devises en code ISO 4217 et les montants en nombres.
- **EF-EXT-3** — L'application doit extraire les lignes de facture : libellé tel qu'imprimé, nom générique du produit, catégorie, quantité, unité normalisée, prix unitaire et total de ligne.
- **EF-EXT-4** — L'application doit marquer comme douteux chaque champ dont l'automate n'est pas sûr, et doit conserver une remarque lisible qui explique le doute.
- **EF-EXT-5** — L'application doit conserver, pour chaque champ douteux, la zone de la page où il se trouve, et doit écarter toute zone invalide (page inexistante, surface nulle, champ non douteux) ou débordant de la page.
- **EF-EXT-6** — L'application doit envoyer toutes les pages d'un document (5 au plus) en un seul appel, pour que l'en-tête et le récapitulatif final soient lus ensemble.
- **EF-EXT-7** — L'application doit redresser une photo selon son orientation EXIF avant de l'envoyer, pour que les zones douteuses correspondent à l'image affichée.
- **EF-EXT-8** — L'application doit transformer un échec d'extraction (API indisponible, réponse vide ou invalide) en ligne en erreur, visible dans l'onglet « En erreur », plutôt que de perdre le document.
- **EF-EXT-9** — L'application doit appliquer, lors de chaque extraction, toutes les règles apprises de l'espace.

### 3.3 Accueil (`ACC`)

- **EF-ACC-1** — L'accueil doit afficher le total facturé du dernier mois complet (pas du mois en cours), dans la devise principale de ce mois, et doit lister les autres devises à côté sans les additionner.
- **EF-ACC-2** — L'accueil doit afficher le nombre de factures de ce mois et le nombre de factures à vérifier, avec un lien vers cette liste.
- **EF-ACC-3** — L'accueil doit afficher l'évolution du total mensuel sur 12 mois au plus, mois en cours compris, dans une seule devise.
- **EF-ACC-4** — L'accueil doit afficher une carte de chaleur des montants par jour et par fournisseur, limitée aux 12 premiers fournisseurs et aux 45 jours les plus récents.
  - Chaque case doit donner son montant au survol et dans une infobulle.
- **EF-ACC-5** — L'accueil doit afficher le dernier import (en cours, terminé ou interrompu), les trois plus fortes alertes de prix et les dernières factures importées.
- **EF-ACC-6** — L'accueil ne doit proposer aucun filtre : il porte toujours sur tout l'espace.

### 3.4 Factures (`FAC`)

- **EF-FAC-1** — La page Factures doit présenter la liste des factures à gauche et la facture sélectionnée à droite ; la sélection doit figurer dans l'adresse (`?id=`).
- **EF-FAC-2** — La page doit permettre de filtrer par recherche, fournisseur, période, statut (toutes, à vérifier, en erreur) et import, et de trier par date ou par montant, croissant ou décroissant.
  - Les compteurs des onglets de statut ignorent le filtre de statut.
- **EF-FAC-3** — La liste doit être paginée par 100 factures, et la pagination doit conserver filtres et tri.
- **EF-FAC-4** — La page doit afficher le document original page par page, avec zoom (de 0,5 à 4 fois la taille ajustée), déplacement à la souris, au doigt et au clavier, et passage d'une page à l'autre.
- **EF-FAC-5** — La visionneuse doit entourer sur le document la zone de chaque champ douteux, doit pouvoir centrer la zone suivante, et un clic sur une zone doit placer le curseur dans le champ correspondant.
- **EF-FAC-6** — L'utilisateur doit pouvoir corriger les six champs d'en-tête, et aucun autre champ ; la correction doit être enregistrée sur la facture dont la valeur a été saisie.
- **EF-FAC-7** — L'utilisateur doit pouvoir confirmer un champ douteux sans le modifier, ou valider la facture entière, ce qui confirme tous ses champs douteux ; une facture en erreur ne doit pas pouvoir être validée.
- **EF-FAC-8** — L'application doit exporter en Excel la liste filtrée et triée, avec le code couleur de la vérification : orange pour un champ douteux, vert pour un champ corrigé.
- **EF-FAC-9** — La page doit rester utilisable sur téléphone : le détail s'ouvre en plein écran avec un bouton retour, sans défilement horizontal de la page.

### 3.5 Produits (`PRO`)

- **EF-PRO-1** — La page Produits doit regrouper les lignes de facture par produit générique, fournisseur, unité et devise, et doit les ordonner par catégorie puis par produit.
- **EF-PRO-2** — L'application doit traiter comme un même produit les variantes de lecture d'un même libellé chez un même fournisseur (casse, accents, pluriel, unité lue différemment), et doit signaler un groupe dont l'unité a été lue de façon incohérente.
- **EF-PRO-3** — L'application doit fusionner deux orthographes d'un fournisseur seulement quand les mots de l'une, formes juridiques ôtées, sont inclus dans ceux de l'autre.
  - Cette fusion ne doit s'appliquer qu'à la page Produits.
- **EF-PRO-4** — Pour chaque groupe, la page doit afficher le prix unitaire moyen, minimum et maximum, le nombre de factures, et un lien vers la facture du prix minimum et du prix maximum.
- **EF-PRO-5** — La page doit signaler les groupes dont le prix maximum dépasse la moyenne de plus d'un seuil réglable (25 % par défaut, de 0 à 100 % par pas de 5 %), sans recharger la page, et les filtres doivent conserver ce seuil.
- **EF-PRO-6** — La page doit afficher l'historique du prix unitaire d'un produit choisi, fournisseur par fournisseur.

### 3.6 Règles apprises (`REG`)

- **EF-REG-1** — L'application doit enregistrer chaque correction et chaque confirmation d'un champ, avec sa valeur avant et après.
- **EF-REG-2** — L'application doit déduire des corrections et confirmations en attente une règle d'extraction par fournisseur (plus une règle globale), et doit affiner la règle existante plutôt que d'en ajouter une nouvelle.
- **EF-REG-3** — L'application doit lancer cet apprentissage automatiquement dès que 3 corrections ou confirmations sont en attente (`AUTO_LEARN_THRESHOLD`), et doit aussi permettre de le lancer à la main.
- **EF-REG-4** — L'application doit marquer comme traitées toutes les corrections analysées, même celles dont aucune règle n'a pu être tirée.
- **EF-REG-5** — L'utilisateur doit pouvoir consulter et supprimer les règles apprises.

### 3.7 Administration (`ADM`)

- **EF-ADM-1** — L'administrateur doit pouvoir lister les espaces clients avec leur espace occupé et leur quota (`manage.py tenants`).
- **EF-ADM-2** — L'administrateur doit pouvoir créer un espace client (`add-tenant`), y créer un compte (`add-user`) et changer le mot de passe d'un compte (`reset-password`).
- **EF-ADM-3** — L'administrateur doit pouvoir consulter le détail de l'espace occupé par un client (`storage`) et fixer son quota en Mo, 0 voulant dire illimité (`set-quota`).

## 4. Exigences non fonctionnelles

### 4.1 Performances et coûts (`PERF`)

- **ENF-PERF-1** — L'application doit traiter au plus 8 documents en parallèle (`MAX_CONCURRENT_EXTRACTIONS`), pour rester dans les limites de débit de l'API.
  - Mesure du 17 septembre 2026 sur 24 factures réelles :
    - environ 10 s par facture pour un traitement seul, dont 71 % passés dans l'appel à
      l'automate ;
    - 1,58 s par facture en lot, soit environ 31 min pour les 1 181 factures du jeu de
      référence.
- **ENF-PERF-2** — L'application doit refaire jusqu'à 6 tentatives d'un appel en cas de surcharge de l'API (erreurs 429 et 529) avant de déclarer l'extraction en échec.
- **ENF-PERF-3** — L'application doit placer les consignes système, règles apprises comprises, en cache d'API : elles sont identiques pour toutes les factures d'un import.
  - Mesure de septembre : environ 7 $ économisés sur un lot de 1 181 factures.
- **ENF-PERF-4** — L'application doit limiter le nombre de règles injectées à 60 (`MAX_RULES_IN_PROMPT`), et doit réduire les images à 2 000 pixels sur le grand côté.
- **ENF-PERF-5** — L'application ne doit pas lire une archive en entier en mémoire décompressée : chaque document est lu au moment où un traitement le prend en charge.
- **ENF-PERF-6** — L'apprentissage des règles, qui est un appel bloquant de plusieurs secondes, doit s'exécuter hors de la boucle d'événements du serveur, pour ne pas figer les autres requêtes.

### 4.2 Stockage et quota (`STO`)

- **ENF-STO-1** — L'application doit mesurer l'espace occupé par un client sur le disque (originaux et fichiers SQLite, y compris `-wal` et `-shm`), et non en additionnant les tailles déclarées.
- **ENF-STO-2** — L'application doit refuser un import quand le quota est déjà atteint, et doit arrêter un import en cours au quota, en transformant chaque fichier refusé en ligne en erreur.
- **ENF-STO-3** — L'application ne doit pas recompresser les originaux : ils sont conservés à l'identique, pour garder leur valeur de copie fidèle.
  - Mesure de septembre : environ 1,1 Mo par facture et environ 2 Go par client et par an.
- **ENF-STO-4** — L'application doit refuser une requête d'import qui dépasse `MAX_UPLOAD_MB` (500 Mo par défaut).

### 4.3 Sécurité (`SEC`)

- **ENF-SEC-1** — L'application ne doit jamais insérer un texte venu d'un document (fournisseur, remarques, libellés) comme du HTML : seulement comme du texte.
- **ENF-SEC-2** — L'application doit envoyer une politique de sécurité du contenu qui interdit tout script en ligne ou tiers (`script-src 'self'`).
- **ENF-SEC-3** — L'application doit dériver le nom de stockage d'un original de l'identifiant de la facture, ne doit accepter qu'une extension de la forme `^\.[a-z0-9]{1,8}$`, et doit vérifier que le chemin final reste dans le dossier du client.
- **ENF-SEC-4** — L'application doit revérifier ce confinement avant de servir un original ou une page rendue, et ne doit servir dans le navigateur que les PDF et les images (JPEG, PNG, WebP).
- **ENF-SEC-5** — L'application doit refuser une session dont l'espace client n'est pas celui de l'adresse demandée, ou dont le compte n'existe plus.
- **ENF-SEC-6** — L'application doit vider la session avant d'en ouvrir une nouvelle à la connexion.
- **ENF-SEC-7** — L'application doit bloquer pendant 5 minutes un couple adresse e-mail + adresse IP après 5 échecs de connexion.
- **ENF-SEC-8** — L'application doit stocker les mots de passe hachés avec scrypt.
- **ENF-SEC-9** — L'application doit marquer le cookie de session `Secure` dès que `APP_DOMAIN` est défini, et doit le garder en `SameSite=Lax`, qui tient lieu de protection CSRF.
- **ENF-SEC-10** — L'application doit autoriser l'affichage dans un cadre de la même origine seulement (`SAMEORIGIN`, `frame-ancestors 'self'`), jamais `DENY` ni `'none'`.
- **ENF-SEC-11** — L'application doit interdire la mise en cache des réponses sous `/invoices`, `/api` et `/dashboard`, et des images de pages.
- **ENF-SEC-12** — L'application doit refuser la modification de tout champ hors des six champs d'en-tête modifiables (`db.EDITABLE_FIELDS`).

### 4.4 Isolation des clients (`ISO`)

- **ENF-ISO-1** — Chaque espace client doit avoir sa propre base SQLite et son propre dossier de fichiers, sans table partagée ni colonne d'espace.
- **ENF-ISO-2** — L'application doit déterminer l'espace client à partir de l'adresse demandée (sous-domaine de `APP_DOMAIN`), et un sous-domaine inconnu doit recevoir une erreur 404 au lieu de créer un espace.
- **ENF-ISO-3** — L'application doit appliquer chaque évolution de schéma à toutes les bases existantes par des migrations additives, à la première ouverture de chaque base.

### 4.5 Compatibilité (`COMP`)

- **ENF-COMP-1** — L'application doit fonctionner sous Python 3.8 (version installée sur le poste de développement) : pas de syntaxe PEP 585 ou 604 évaluée à l'exécution, notamment dans les signatures des routes.
- **ENF-COMP-2** — L'application doit s'installer et se lancer sur un poste Windows par `Installer.bat` et `Lancer.bat`, sans ligne de commande.
- **ENF-COMP-3** — L'application doit fonctionner dans les navigateurs récents sur ordinateur et sur téléphone, sans étape de construction du front (une feuille de style, un script).

### 4.6 Conventions d'interface (`UI`)

- **ENF-UI-1** — L'interface ne doit jamais nommer le modèle : elle doit dire « l'automate ».
- **ENF-UI-2** — Tous les boutons doivent partager une même couleur ; le bleu doit être réservé aux liens et au focus.
- **ENF-UI-3** — L'interface doit respecter le réglage « réduire les animations » : les mouvements deviennent instantanés, et une action au clavier ne doit jamais être animée.
- **ENF-UI-4** — La couleur ne doit jamais être le seul moyen de lire une information : chaque case de la carte de chaleur porte aussi sa valeur en texte, et sa rampe de couleurs doit décroître en luminosité.
- **ENF-UI-5** — L'application doit référencer la feuille de style et le script avec un numéro de version (`static_url`), pour qu'une mise à jour ne laisse pas l'ancien script en cache.
