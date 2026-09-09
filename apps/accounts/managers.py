"""Managers pour le modèle User."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.auth.base_user import BaseUserManager
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from .models import User


class UserManager(BaseUserManager["User"]):
    """Manager créant des utilisateurs identifiés par login."""

    use_in_migrations = True

    def normalize_identifier(self, value: str) -> str:
        """Normalise l'identifiant : e-mails en minuscules, sinon conserve la casse."""
        value = (value or "").strip()
        if "@" in value:
            return self.normalize_email(value)
        return value

    def _create_user(self, email: str, password: str | None, **extra_fields: Any) -> User:
        """Crée et sauvegarde un utilisateur avec identifiant et mot de passe."""
        if not email:
            raise ValueError(_("L'identifiant est obligatoire."))
        email = self.normalize_identifier(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> User:
        """Crée un utilisateur standard."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> User:
        """Crée un superutilisateur."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Le superutilisateur doit avoir is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Le superutilisateur doit avoir is_superuser=True."))

        return self._create_user(email, password, **extra_fields)
