"""Modèle User personnalisé (identifiant de connexion)."""

from __future__ import annotations

import uuid
from typing import ClassVar

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .managers import UserManager


class MinistryRole(models.TextChoices):
    """Rôle ministériel pour le circuit de validation des procurations."""

    ADMIN = "admin", _("Administrateur")
    CONSEILLER = "conseiller", _("Conseiller")
    DIRCABA = "dircaba", _("Dircaba")
    CHARGE_ETUDES = "charge_etudes", _("Chargé d'Études")
    GREFFE = "greffe", _("Greffe")


class User(AbstractBaseUser, PermissionsMixin):
    """Utilisateur AvoLex authentifié par identifiant (e-mail ou nom)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.CharField(_("identifiant"), max_length=254, unique=True, db_index=True)
    first_name = models.CharField(_("prénom"), max_length=150, blank=True)
    last_name = models.CharField(_("nom"), max_length=150, blank=True)
    phone = models.CharField(_("téléphone"), max_length=32, blank=True)
    is_staff = models.BooleanField(
        _("statut équipe"),
        default=False,
        help_text=_("Indique si l'utilisateur peut accéder à l'admin Django."),
    )
    is_platform_admin = models.BooleanField(
        _("administrateur ministère"),
        default=False,
        db_index=True,
        help_text=_(
            "Administrateur du Ministère de la Justice : cabinets, dossiers, procurations."
        ),
    )
    is_super_admin = models.BooleanField(
        _("super administrateur"),
        default=False,
        db_index=True,
        help_text=_(
            "SuperAdmin : tous les droits, création des administrateurs et comptes cabinets."
        ),
    )
    ministry_role = models.CharField(
        _("rôle ministériel"),
        max_length=20,
        choices=MinistryRole.choices,
        blank=True,
        default="",
        db_index=True,
        help_text=_(
            "Administrateur / Chargé d'Études : émission. "
            "Conseiller : 1re validation. Dircaba : visa final. Greffe : consultation."
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
        """Retourne le nom complet, ou l'identifiant à défaut."""
        name = f"{self.first_name} {self.last_name}".strip()
        return name or self.email

    def get_full_name(self) -> str:
        """Compatibilité API Django auth."""
        return self.full_name

    def get_short_name(self) -> str:
        """Retourne le prénom ou la partie locale de l'identifiant."""
        if self.first_name:
            return self.first_name
        if "@" in self.email:
            return self.email.split("@", maxsplit=1)[0]
        return self.email
