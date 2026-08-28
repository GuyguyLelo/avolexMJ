"""Crée (ou met à jour) un compte administrateur plateforme."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    """Crée un utilisateur is_platform_admin pour superviser tous les cabinets."""

    help = (
        "Crée ou met à jour un administrateur plateforme "
        "(supervision de tous les cabinets, CRUD cabinets avocats)."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[no-untyped-def]
        parser.add_argument(
            "--email",
            default="supervision@avolex.local",
            help="E-mail du compte (défaut: supervision@avolex.local)",
        )
        parser.add_argument(
            "--password",
            default="@Supervise123",
            help="Mot de passe (défaut: @Supervise123)",
        )
        parser.add_argument("--first-name", default="Supervision", dest="first_name")
        parser.add_argument("--last-name", default="AvoLex", dest="last_name")

    def handle(self, *args: object, **options: object) -> None:
        email = str(options["email"]).strip().lower()
        password = str(options["password"])
        first_name = str(options["first_name"])
        last_name = str(options["last_name"])

        if not email or "@" not in email:
            raise CommandError("E-mail invalide.")

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

        user.is_platform_admin = True
        user.is_active = True
        user.save()

        action = "créé" if created else "mis à jour"
        self.stdout.write(
            self.style.SUCCESS(
                f"Administrateur plateforme {action} : {user.email} "
                f"(supervision + gestion des cabinets avocats)."
            )
        )
        self.stdout.write(f"  Connexion : {email}")
        self.stdout.write(f"  Mot de passe : {password}")
        self.stdout.write("  Accueil : /app/supervision/")
