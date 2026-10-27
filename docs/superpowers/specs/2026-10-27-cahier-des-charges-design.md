# Cahier des charges de The Bill Please — conception

Date : 27 octobre 2026 · Branche : `claude/cahier-des-charges` (depuis `main`, 23d0c3e)

## Intention

Océane veut une **référence de l'existant** de l'application, en deux versions :

- une **version technique**, pour elle et son co-développeur ;
- une **version client / investisseur**, à présenter à un tiers.

Elle veut aussi pouvoir estimer combien de factures elle peut encore traiter avec le crédit
API restant. Dans les documents, cela prend la forme d'un coût par facture et d'une formule.
Dans l'application, ce sera une fonctionnalité conçue à part (voir « Hors périmètre »).

**Ce qu'elle a dit :**

- l'existant décrit est `main` + la PR #4 (page Factures), supposée fusionnée avant diffusion ;
- la version investisseur contient les chiffres mesurés, la sécurité et le RGPD, les limites
  actuelles et des captures d'écran ;
- emplacement : la version technique dans le dépôt, la version investisseur en document
  partageable ;
- les deux plans de document présentés en conversation sont validés.

**Hypothèses retenues :**

- les deux documents sont rédigés en français ;
- ils décrivent l'existant, sans feuille de route ni chiffres de marché ;
- `CLAUDE.md` reste le guide de développement : la version technique énonce des exigences
  et y renvoie pour le détail, sans le recopier.

**Critère de réussite :**

- chaque affirmation des deux documents est vraie pour le code de `main` + PR #4 ;
- chaque chiffre est daté et sourcé (constante du code, mesure documentée ou tarif public
  vérifié) ;
- un lecteur non technique comprend la version investisseur sans aide.

## Livrable 1 — `docs/cahier-des-charges-technique.md`

Fichier Markdown versionné, relu en PR. Plan validé :

1. **Objet et périmètre.** État décrit (`main` + PR #4, date), lien avec `CLAUDE.md`, et ce
   que le document remplace dans les trois PDF de `docs/` (voir « Documents existants »).
2. **Acteurs.**
   - l'utilisateur d'un espace client ;
   - l'administrateur, qui crée espaces, comptes et quotas par `manage.py`.
3. **Exigences fonctionnelles.** Identifiants `EF-<domaine>-<n>` : `IMP` import, `EXT`
   extraction, `ACC` accueil, `FAC` factures, `PRO` produits, `REG` règles apprises, `ADM`
   administration. Chacune est une phrase vérifiable (« l'application doit… »), suivie si
   besoin d'une ligne de justification.
4. **Exigences non fonctionnelles.** Identifiants `ENF-<domaine>-<n>` :
   - `PERF` performances et coûts ;
   - `STO` stockage et quota ;
   - `SEC` sécurité, un invariant de `CLAUDE.md` par exigence ;
   - `ISO` isolation des clients ;
   - `COMP` compatibilité ;
   - `UI` conventions d'interface.
5. **Architecture.**
   - les modules et leur rôle ;
   - le parcours d'une facture, de l'import à l'écran, en diagramme Mermaid (rendu
     nativement par GitHub) ;
   - le modèle de données, table par table, colonnes clés comprises (`import_log`, colonnes
     ajoutées par la PR #4) ;
   - la dépendance à l'API Claude : modèles, paramètres, cache, nouvelles tentatives.
6. **Hypothèses et limites connues.** Les hypothèses de `CLAUDE.md` (« Key assumptions »), plus
   les petits défauts différés de la PR #4.
7. **Coût et capacité restante.** Coût estimé d'une facture (méthode ci-dessous), formule
   `factures restantes ≈ crédit restant ÷ coût par facture`, tableau d'exemples (10 $, 50 $,
   100 $).
8. **Traçabilité.** Tableau exigence → test(s) qui la vérifient, au nom de fichier et de
   fonction près. Une exigence sans test est marquée **non couverte**. La suite de sécurité
   citée par `CLAUDE.md` n'existe pas dans le dépôt : les invariants de sécurité sans test sont
   donc marqués non couverts, avec une note qui le signale.

## Livrable 2 — document Claude « The Bill Please — présentation »

Document partageable (type Docs), exportable en PDF ou Word. Ton : clair, sans jargon. Le modèle
est appelé « l'automate », comme dans l'application ; Anthropic n'est nommé qu'en section 6
(données envoyées à l'API) et Claude qu'en section 8. Plan validé :

1. **Le problème.**
2. **La solution en une phrase**, puis le parcours en 4 étapes : importer → l'automate lit →
   on vérifie seulement le douteux → on analyse.
3. **Les écrans.** Captures commentées des images déjà commitées :
   - `2026-10-25-accueil-brume-ordinateur.png` (accueil) ;
   - `2026-10-26-factures-liste-detail.png` (liste et détail) ;
   - `2026-10-26-factures-zone-douteuse.png` (zone douteuse) ;
   - `2026-10-26-factures-bilan-import.png` (bilan d'import) ;
   - `2026-10-26-factures-telephone.png` (téléphone).

   Elles montrent des données de test : une mention le précise.
4. **Ce qui la distingue.**
   - elle signale ses doutes et les montre sur le document ;
   - elle apprend des corrections, fournisseur par fournisseur ;
   - un doublon n'est jamais compté deux fois ;
   - elle suit la dérive des prix par produit.
5. **Chiffres mesurés.** Temps de traitement, stockage, coût par facture et capacité (même
   méthode que le livrable 1). Chaque chiffre porte sa date de mesure.
6. **Sécurité et RGPD.**
   - isolation par client ;
   - documents servis après connexion ;
   - effacement d'un client en une opération ;
   - données envoyées à l'API : reprend la note RGPD de septembre, avec ses sources et son
     avertissement « pas un avis juridique ».
7. **Limites actuelles.**
   - installation sur poste Windows, pas d'hébergement ;
   - lignes de facture et zones absentes des anciens imports ;
   - une facture par document ;
   - page Produits pas encore refaite ;
   - totaux multi-devises non convertis ;
   - comptes gérés en ligne de commande, sans mot de passe oublié ni double authentification.
8. **Sous le capot.** Un paragraphe, puis un renvoi au document technique.

## Méthode d'estimation du coût par facture

Aucune clé API n'est disponible dans l'environnement de rédaction, et celle d'Océane ne doit
pas être utilisée. Le coût est donc **calculé**, pas mesuré à nouveau :

- **entrée** :
  - ~2 900 jetons par page d'image (mesure de septembre, rendu 150 dpi inchangé) ;
  - consignes système de 1 270 jetons (sans règle) à 6 900 jetons (60 règles), lues
    depuis le cache au tarif cache après le premier appel d'un lot ;
- **sortie** : le budget est de 8 192 jetons, mais une réponse réelle est bien plus courte.
  La fourchette s'appuie sur la mesure documentée dans `CLAUDE.md` (« un demi-centime à un
  centime par facture » en sortie) ;
- **tarif** : tarif public du modèle `claude-sonnet-5`, vérifié sur la page de tarifs
  d'Anthropic le jour de la rédaction, et cité avec sa date.

Le résultat est une **fourchette**, avec un cas bas (1 page, peu de règles, réponse courte) et
un cas haut (3 pages, 60 règles, 40 lignes). Elle est comparée à l'estimation de septembre
(« 10 à 12 € pour 1 000 factures »), qui précède l'extraction des lignes. Les deux documents
précisent que la mesure réelle viendra de la fonctionnalité prévue dans l'application.

## Documents existants

Les trois PDF de `docs/` (architecture et note RGPD de septembre, guide d'installation) restent
dans le dépôt : ce sont des documents datés. La section 1 du livrable 1 liste ce qui a changé
depuis :

- table `duplicates` remplacée par `import_log` ;
- panneau des doublons supprimé ;
- `max_tokens` porté de 2 048 à 8 192 ;
- lignes de facture, zones douteuses et confirmations ajoutées.

## Vérification

- **Exactitude :** chaque exigence est confrontée au code de `main` + PR #4 par un relecteur
  indépendant (agent sans contexte), qui signale toute affirmation fausse ou invérifiable.
- **Traçabilité :** chaque test cité existe (vérifié par `pytest --collect-only` sur la branche
  de la PR #4).
- **Chiffres :** chacun renvoie à sa source dans le document.
- **Rendu :** le document partageable est relu une fois publié ; le Markdown est vérifié dans
  l'aperçu GitHub de la PR.

## Hors périmètre

- **La mesure de la consommation réelle dans l'application** (jetons par appel, coût moyen
  affiché, capacité restante) : conception séparée après ces documents, avec son propre
  cycle conception → plan → code.
- La feuille de route, les chiffres de marché et la tarification commerciale.
- Toute modification du code ou des trois PDF existants.
- La correction des invariants de sécurité non couverts par des tests : ce manque est
  signalé, pas comblé ici.

## Fusion

La PR de ces documents décrit le code de la PR #4. Elle doit être fusionnée **après** la PR #4 ;
sa description le précise.
