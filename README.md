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

## Notes

- Un fichier = une facture (éventuellement plusieurs pages pour un même PDF).
- Formats acceptés : PDF, JPG, PNG, WEBP.
- Coût estimé : quelques centimes pour 1000 factures avec Claude Sonnet 5 (voir la
  documentation Anthropic pour le détail des tarifs).
- Si une facture pose problème (champ illisible, refus du modèle...), la ligne correspondante
  dans l'Excel contient une colonne "Erreur" ou "Remarques" expliquant pourquoi.
