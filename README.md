# Extraction de factures

Petite application web locale : dépose une ou plusieurs factures (PDF ou photos), l'IA
(Claude Sonnet 5, vision) extrait le fournisseur, le numéro de facture, la date, le montant
total et la TVA, puis génère un fichier Excel (une ligne par facture).

## Prérequis

- Python (testé avec Anaconda Python 3.8.8)
- Une clé API Anthropic : crée-en une sur https://console.anthropic.com (Settings > API Keys)

## Installation

L'environnement virtuel `.venv` est déjà créé avec toutes les dépendances installées. Pour le
recréer depuis zéro si besoin :

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Copie `.env.example` en `.env` et colle ta clé API dedans :

```
copy .env.example .env
```

Puis édite `.env` et remplace `sk-ant-...` par ta vraie clé.

## Lancer l'application

```
.venv\Scripts\activate
python app.py
```

Ouvre ensuite http://127.0.0.1:8000 dans ton navigateur, dépose tes factures et clique sur
"Extraire et générer l'Excel".

## Dossiers compressés (.zip)

Tu peux déposer directement une archive `.zip` contenant des factures, y compris rangées en
sous-dossiers (par mois, par fournisseur...). L'outil parcourt l'archive, traite chaque PDF
ou image trouvé, et ajoute une colonne "Archive" dans l'Excel pour savoir d'où vient chaque
ligne.

- Les factures sont traitées **8 en parallèle** : compte environ 30 à 45 minutes pour un lot
  de 1000 factures (au lieu de plusieurs heures une par une).
- Pendant le traitement, l'avancement s'affiche dans la fenêtre noire du serveur
  (`Factures traitees : 120/1181`). Le fichier Excel n'est téléchargé qu'à la toute fin.
- Conseil : commence par déposer **une seule archive** pour vérifier le résultat avant de
  lancer un gros lot.
- Les fichiers qui ne sont ni des PDF ni des images (documents Word, etc.) apparaissent quand
  même dans l'Excel, avec une erreur expliquant qu'ils ont été ignorés — rien ne disparaît
  silencieusement.

## Notes

- Un fichier = une facture (éventuellement plusieurs pages pour un même PDF). Si un même PDF
  contient en réalité plusieurs factures, seule la première est extraite et une remarque le
  signale dans l'Excel.
- Formats acceptés : PDF, JPG, PNG, WEBP, et archives ZIP contenant ces formats.
- Coût estimé : environ 1 centime par facture avec Claude Sonnet 5, soit ~10 € pour 1000
  factures (voir la documentation Anthropic pour le détail des tarifs).
- Si une facture pose problème (champ illisible, refus du modèle...), la ligne correspondante
  dans l'Excel contient une colonne "Erreur" ou "Remarques" expliquant pourquoi.
