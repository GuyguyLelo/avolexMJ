"""Modèles clients (socle requis par dossiers / GED)."""

from __future__ import annotations

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantOwnedModel


class ClientType(models.TextChoices):
    """Type de client."""

    PERSON = "person", _("Personne physique")
    COMPANY = "company", _("Personne morale")


class Client(TenantOwnedModel):
    """Client du cabinet (personne physique ou morale)."""

    client_type = models.CharField(
        _("type"),
        max_length=16,
        choices=ClientType.choices,
        default=ClientType.PERSON,
        db_index=True,
    )
    first_name = models.CharField(_("prénom"), max_length=150, blank=True)
    last_name = models.CharField(_("nom"), max_length=150, blank=True)
    birth_date = models.DateField(_("date de naissance"), null=True, blank=True)
    company_name = models.CharField(_("raison sociale"), max_length=255, blank=True)
    siret = models.CharField(_("SIRET"), max_length=14, blank=True)
    legal_form = models.CharField(_("forme juridique"), max_length=64, blank=True)
    email = models.EmailField(_("e-mail"), blank=True)
    phone = models.CharField(_("téléphone"), max_length=40, blank=True)
    address_line1 = models.CharField(_("adresse"), max_length=255, blank=True)
    address_line2 = models.CharField(_("complément d'adresse"), max_length=255, blank=True)
    postal_code = models.CharField(_("code postal"), max_length=20, blank=True)
    city = models.CharField(_("ville"), max_length=100, blank=True)
    country = models.CharField(_("pays"), max_length=2, default="FR")
    notes = models.TextField(_("notes"), blank=True)
    search_vector = SearchVectorField(_("vecteur de recherche"), null=True, editable=False)

    class Meta:
        verbose_name = _("Client")
        verbose_name_plural = _("Clients")
        ordering = ("-updated_at",)
        indexes = [
            GinIndex(fields=["search_vector"], name="clients_client_search_gin"),
            models.Index(
                fields=["cabinet", "last_name", "first_name"],
                name="clients_cli_cabinet_410376_idx",
            ),
            models.Index(
                fields=["cabinet", "company_name"],
                name="clients_cli_cabinet_176387_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.display_name

    @property
    def display_name(self) -> str:
        """Nom affiché selon le type de client."""
        if self.client_type == ClientType.COMPANY:
            return self.company_name or str(_("(Société sans nom)"))
        name = f"{self.first_name} {self.last_name}".strip()
        return name or str(_("(Client sans nom)"))
