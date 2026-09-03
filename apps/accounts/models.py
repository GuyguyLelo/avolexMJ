"""Modèle User personnalisé (e-mail comme identifiant)."""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """Utilisateur AvoLex authentifié par adresse e-mail."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(_("adresse e-mail"), unique=True, db_index=True)
    first_name = models.CharField(_("prénom"), max_length=150, blank=True)
    last_name = models.CharField(_("nom"), max_length=150, blank=True)
    phone = models.CharField(_("téléphone"), max_length=32, blank=True)
    is_staff = models.BooleanField(
        _("statut équipe"),
        default=False,
        help_text=_("Indique si l'utilisateur peut accéder à l'admin Django."),
    )
    is_platform_admin = models.BooleanField(
        _("administrateur plateforme"),
        default=False,
        db_index=True,
        help_text=_(
            "Supervise tous les cabinets en lecture seule (suivi d'activité cross-cabinet)."
        ),
    )
    is_active = models.BooleanField(
        _("actif"),
        default=True,
        help_text=_("Désactiver plutôt que supprimer un compte."),
    )
    date_joined = models.DateTimeField(_("date d'inscription"), default=timezone.now)
    timezone = models.CharField(
        _("fuseau horaire"),
        max_length=63,
        default="Europe/Paris",
    )
    locale = models.CharField(_("langue"), max_length=10, default="fr")

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        verbose_name = _("Utilisateur")
        verbose_name_plural = _("Utilisateurs")
        ordering = ("email",)

    def __str__(self) -> str:
        return self.email

    @property
    def full_name(self) -> str:
        """Retourne le nom complet, ou l'e-mail à défaut."""
        name = f"{self.first_name} {self.last_name}".strip()
        return name or self.email

    def get_full_name(self) -> str:
        """Compatibilité API Django auth."""
        return self.full_name

    def get_short_name(self) -> str:
        """Retourne le prénom ou la partie locale de l'e-mail."""
        return self.first_name or self.email.split("@", maxsplit=1)[0]
