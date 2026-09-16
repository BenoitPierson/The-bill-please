"""Administration CLI — provisioning client workspaces and accounts.

    python manage.py tenants
    python manage.py add-tenant acme --name "ACME SARL"
    python manage.py add-user acme compta@acme.fr
    python manage.py reset-password acme compta@acme.fr
"""
from __future__ import annotations

import argparse
import getpass
import sqlite3
import sys

from dotenv import load_dotenv

load_dotenv()

import auth  # noqa: E402  (after load_dotenv, like the app does)
import db  # noqa: E402
import tenants  # noqa: E402


def _read_password() -> str:
    while True:
        password = getpass.getpass("Mot de passe : ")
        problem = auth.password_problem(password)
        if problem:
            print(problem)
            continue
        if password != getpass.getpass("Confirmer    : "):
            print("Les mots de passe ne correspondent pas.")
            continue
        return password


def cmd_tenants(_args) -> int:
    slugs = tenants.list_slugs()
    if not slugs:
        print("Aucun espace client. Cree le premier avec : python manage.py add-tenant <slug>")
        return 0
    for slug in slugs:
        with db.connect(slug) as conn:
            users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
            invoices = conn.execute("SELECT COUNT(*) AS n FROM invoices").fetchone()["n"]
        print(
            "{:<20} {:<28} {:>4} utilisateur(s)  {:>6} facture(s)".format(
                slug, tenants.display_name(slug), users, invoices
            )
        )
    return 0


def cmd_add_tenant(args) -> int:
    if not tenants.is_valid_slug(args.slug):
        print("Identifiant invalide. Utilise des minuscules, chiffres et tirets (ex: acme-sarl).")
        return 1
    existed = tenants.exists(args.slug)
    tenants.create(args.slug, args.name)
    db.count_users(args.slug)  # forces schema creation
    print(
        "Espace {} {}.".format(args.slug, "deja present, verifie" if existed else "cree")
    )
    print("URL de production attendue : https://{}.<votre-domaine>".format(args.slug))
    print("Ajoute un compte avec : python manage.py add-user {} <email>".format(args.slug))
    return 0


def cmd_add_user(args) -> int:
    if not tenants.exists(args.slug):
        print("Espace inconnu : {}".format(args.slug))
        return 1
    try:
        db.create_user(args.slug, args.email, auth.hash_password(_read_password()))
    except sqlite3.IntegrityError:
        print("Un compte existe deja pour {} sur cet espace.".format(args.email))
        return 1
    print("Compte {} cree sur l'espace {}.".format(args.email, args.slug))
    return 0


def cmd_reset_password(args) -> int:
    if db.get_user(args.slug, args.email) is None:
        print("Compte introuvable : {} sur {}".format(args.email, args.slug))
        return 1
    with db.connect(args.slug) as conn:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE email = ? COLLATE NOCASE",
            (auth.hash_password(_read_password()), args.email),
        )
    print("Mot de passe mis a jour pour {}.".format(args.email))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Administration de la plateforme de factures")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("tenants", help="Lister les espaces clients").set_defaults(func=cmd_tenants)

    add_tenant = sub.add_parser("add-tenant", help="Creer un espace client")
    add_tenant.add_argument("slug")
    add_tenant.add_argument("--name", default=None, help="Nom affiche (ex: \"ACME SARL\")")
    add_tenant.set_defaults(func=cmd_add_tenant)

    add_user = sub.add_parser("add-user", help="Creer un compte sur un espace")
    add_user.add_argument("slug")
    add_user.add_argument("email")
    add_user.set_defaults(func=cmd_add_user)

    reset = sub.add_parser("reset-password", help="Changer le mot de passe d'un compte")
    reset.add_argument("slug")
    reset.add_argument("email")
    reset.set_defaults(func=cmd_reset_password)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
