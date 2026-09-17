"""Administration CLI — provisioning client workspaces and accounts.

    python manage.py tenants
    python manage.py add-tenant acme --name "ACME SARL"
    python manage.py add-user acme compta@acme.fr
    python manage.py reset-password acme compta@acme.fr
    python manage.py storage acme
    python manage.py set-quota acme 5000        # Mo ; 0 = illimite
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
from charts import format_bytes  # noqa: E402


def _quota_text(slug: str) -> str:
    quota = tenants.storage_quota_bytes(slug)
    if not quota:
        return "illimite"
    used = tenants.storage_usage(slug)["total_bytes"]
    return "{} ({:.0f}%)".format(format_bytes(quota), 100.0 * used / quota)


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
    print("{:<18} {:<26} {:>6} {:>9} {:>10}  {}".format(
        "ESPACE", "NOM", "COMPTES", "FACTURES", "STOCKAGE", "QUOTA"))
    for slug in slugs:
        with db.connect(slug) as conn:
            users = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
            invoices = conn.execute("SELECT COUNT(*) AS n FROM invoices").fetchone()["n"]
        print(
            "{:<18} {:<26} {:>6} {:>9} {:>10}  {}".format(
                slug,
                tenants.display_name(slug)[:26],
                users,
                invoices,
                format_bytes(tenants.storage_usage(slug)["total_bytes"]),
                _quota_text(slug),
            )
        )
    return 0


def cmd_storage(args) -> int:
    if not tenants.exists(args.slug):
        print("Espace inconnu : {}".format(args.slug))
        return 1

    usage = tenants.storage_usage(args.slug)
    duplicates = db.duplicate_summary(args.slug)
    with db.connect(args.slug) as conn:
        stats = conn.execute(
            """
            SELECT COUNT(*) AS n, IFNULL(AVG(file_size), 0) AS mean, IFNULL(MAX(file_size), 0) AS biggest,
                   SUM(CASE WHEN file_size > 5 * 1024 * 1024 THEN 1 ELSE 0 END) AS heavy_count,
                   IFNULL(SUM(CASE WHEN file_size > 5 * 1024 * 1024 THEN file_size ELSE 0 END), 0) AS heavy_bytes
            FROM invoices WHERE file_size IS NOT NULL
            """
        ).fetchone()
        heaviest = conn.execute(
            "SELECT filename, file_size FROM invoices WHERE file_size IS NOT NULL "
            "ORDER BY file_size DESC LIMIT 5"
        ).fetchall()

    print("Espace {} ({})".format(args.slug, tenants.display_name(args.slug)))
    print("  Total occupe          : {}".format(format_bytes(usage["total_bytes"])))
    print("    documents originaux : {} ({} fichier(s))".format(
        format_bytes(usage["files_bytes"]), usage["file_count"]))
    print("    base de donnees     : {}".format(format_bytes(usage["db_bytes"])))
    print("  Quota                 : {}".format(_quota_text(args.slug)))
    if stats["n"]:
        print("  Taille par facture    : moyenne {}, max {}".format(
            format_bytes(stats["mean"]), format_bytes(stats["biggest"])))
        if stats["heavy_count"]:
            print("  Factures > 5 Mo       : {} fichier(s), {} ({:.0f}% des originaux)".format(
                stats["heavy_count"], format_bytes(stats["heavy_bytes"]),
                100.0 * stats["heavy_bytes"] / max(usage["files_bytes"], 1)))
    print("  Doublons ignores      : {} fichier(s), {} evite(s)".format(
        duplicates["count"], format_bytes(duplicates["bytes"])))
    if heaviest:
        print("  Plus gros documents :")
        for row in heaviest:
            print("    {:>9}  {}".format(format_bytes(row["file_size"]), row["filename"]))
    return 0


def cmd_set_quota(args) -> int:
    if not tenants.exists(args.slug):
        print("Espace inconnu : {}".format(args.slug))
        return 1
    if args.megabytes < 0:
        print("Le quota doit etre positif (0 = illimite).")
        return 1
    tenants.set_storage_quota(args.slug, args.megabytes)
    print("Quota de {} : {}".format(args.slug, _quota_text(args.slug)))
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

    storage = sub.add_parser("storage", help="Detail de l'espace occupe par un client")
    storage.add_argument("slug")
    storage.set_defaults(func=cmd_storage)

    quota = sub.add_parser("set-quota", help="Fixer le quota de stockage d'un client")
    quota.add_argument("slug")
    quota.add_argument("megabytes", type=int, help="Quota en Mo (0 = illimite)")
    quota.set_defaults(func=cmd_set_quota)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
