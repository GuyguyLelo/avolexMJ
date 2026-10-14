"""Crée (ou met à jour) un compte SuperAdmin."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.tenants.services import detach_user_from_all_cabinets

User = get_user_model()


class Command(BaseCommand):
    """Crée un SuperAdmin (tous droits + gestion des comptes)."""

    help = (
        "Crée ou met à jour un SuperAdmin "
        "(tous les droits, création des administrateurs et comptes cabinets)."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[no-untyped-def]
        parser.add_argument(
            "--email",
            default="SuperAdmin",
            help="Identifiant de connexion (défaut: SuperAdmin)",
        )
        parser.add_argument(
            "--password",
            default="@SuperAdmin123",
            help="Mot de passe (défaut: @SuperAdmin123)",
        )
        parser.add_argument("--first-name", default="Super", dest="first_name")
        parser.add_argument("--last-name", default="Admin", dest="last_name")
        parser.add_argument(
            "--as-administrator",
            action="store_true",
            help="Crée un compte Ministère (sans SuperAdmin).",
        )

    def handle(self, *args: object, **options: object) -> None:
        raw_email = str(options["email"]).strip()
        password = str(options["password"])
        first_name = str(options["first_name"])
        last_name = str(options["last_name"])
        as_admin = bool(options.get("as_administrator"))

        # Avec --as-administrator, défaut d'identifiant = Admin (pas SuperAdmin).
        if as_admin and raw_email == "SuperAdmin":
            raw_email = "Admin"
            if password == "@SuperAdmin123":
                password = "@Admin12345"

        email = User.objects.normalize_identifier(raw_email)

        if not email:
            raise CommandError("Identifiant invalide.")

        user = User.objects.filter(email__iexact=email).first()
        created = False
        if user is None:
            user = User.objects.create_user(
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )
            created = True
        else:
            user.first_name = first_name
            user.last_name = last_name
            user.set_password(password)

        if as_admin:
            user.is_super_admin = False
            user.is_platform_admin = True
            role_label = "Compte Ministère"
        else:
            user.is_super_admin = True
            user.is_platform_admin = True
            role_label = "SuperAdmin"
        user.is_active = True
        user.save()
        detached = detach_user_from_all_cabinets(user)
        if detached:
            self.stdout.write(f"  Rattachements cabinet retirés : {detached}")

        action = "créé" if created else "mis à jour"
        self.stdout.write(
            self.style.SUCCESS(f"{role_label} {action} : {user.email}")
        )
        self.stdout.write(f"  Connexion : {email}")
        self.stdout.write(f"  Mot de passe : {password}")
        self.stdout.write("  Accueil : /app/supervision/")
