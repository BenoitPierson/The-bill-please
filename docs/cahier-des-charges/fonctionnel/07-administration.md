# Administration

Fait partie du [cahier des charges](../README.md) · état au 27 octobre 2026 (`main` + PR #4).

## Objectif

Créer et suivre les espaces clients et leurs comptes, depuis le serveur.

## Parcours

L'administrateur agit en ligne de commande sur le serveur ; il n'y a pas d'interface web d'administration.

```
python manage.py tenants                            # espaces, espace occupé, quota
python manage.py add-tenant acme --name "ACME SARL" # créer un espace
python manage.py add-user acme compta@acme.fr       # créer un compte
python manage.py reset-password acme compta@acme.fr # changer un mot de passe
python manage.py storage acme                       # détail de l'espace occupé
python manage.py set-quota acme 5000                # quota en Mo, 0 = illimité
```

Tant qu'un espace n'a aucun compte, la page `/setup` permet d'y créer le premier depuis le navigateur.

## Exigences

Chaque exigence indique le test du dépôt qui la vérifie, ou « non couverte ».

- **EF-ADM-1** — L'administrateur doit pouvoir lister les espaces clients avec leur espace occupé et leur quota (`manage.py tenants`).
  - *Test :* **non couverte**
- **EF-ADM-2** — L'administrateur doit pouvoir créer un espace client (`add-tenant`), y créer un compte (`add-user`) et changer le mot de passe d'un compte (`reset-password`).
  - *Test :* **non couverte**
- **EF-ADM-3** — L'administrateur doit pouvoir consulter le détail de l'espace occupé par un client (`storage`) et fixer son quota en Mo, 0 voulant dire illimité (`set-quota`).
  - *Test :* **non couverte**

## Règles de gestion et cas limites

- Un espace client est un dossier ; le système de fichiers sert de registre.
- Seul l'espace par défaut est créé automatiquement ; un sous-domaine inconnu reçoit une erreur 404 (`ENF-ISO-2`).

## Limites connues

- Pas de mot de passe oublié, pas de double authentification, pas de rôles.
- Pas de commande pour supprimer un espace : l'effacement d'un client se fait en supprimant son dossier.
