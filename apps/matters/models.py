"""Modèles dossiers (socle requis par la GED)."""

from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantOwnedModel


class MatterStatus(models.TextChoices):
    """Statut d'un dossier."""

    OPEN = "open", _("Ouvert")
    IN_PROGRESS = "in_progress", _("En cours")
    ON_HOLD = "on_hold", _("En attente")
    CLOSED = "closed", _("Clos")


class MatterScale(models.TextChoices):
    """Échelle de traitement par le Ministère de la Justice."""

    NATIONAL = "national", _("Nationale")
    INTERNATIONAL = "international", _("Internationale")


class Matter(TenantOwnedModel):
    """Dossier / affaire du cabinet."""

    reference = models.CharField(_("référence"), max_length=32, db_index=True)
    title = models.CharField(_("intitulé"), max_length=255)
    description = models.TextField(_("description"), blank=True)
    practice_area = models.CharField(_("matière / domaine"), max_length=120, blank=True)
    jurisdiction = models.CharField(_("juridiction"), max_length=255, blank=True)
    opposing_party = models.CharField(_("partie adverse"), max_length=255, blank=True)
    scale = models.CharField(
        _("échelle"),
        max_length=20,
        choices=MatterScale.choices,
        default=MatterScale.NATIONAL,
        db_index=True,
        help_text=_("Le Ministère de la Justice traite le dossier à l'échelle nationale ou internationale."),
    )
    status = models.CharField(
        _("statut"),
        max_length=20,
        choices=MatterStatus.choices,
        default=MatterStatus.OPEN,
        db_index=True,
    )
    client = models.ForeignKey(
        "clients.Client",
        verbose_name=_("client"),
        on_delete=models.PROTECT,
        related_name="matters",
    )
    responsible_lawyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("avocat responsable"),
        on_delete=models.PROTECT,
        related_name="responsible_matters",
    )
    opened_at = models.DateField(_("ouvert le"), null=True, blank=True)
    closed_at = models.DateField(_("clos le"), null=True, blank=True)
    is_archived = models.BooleanField(_("archivé"), default=False, db_index=True)
    notes = models.TextField(_("notes"), blank=True)
    search_vector = SearchVectorField(_("vecteur de recherche"), null=True, editable=False)

    class Meta:
        verbose_name = _("dossier")
        verbose_name_plural = _("dossiers")
        ordering = ("-updated_at",)
        indexes = [
            GinIndex(fields=["search_vector"], name="matters_matter_search_gin"),
            models.Index(fields=["cabinet", "status"], name="matters_mat_cabinet_47255b_idx"),
            models.Index(fields=["cabinet", "scale"], name="matters_mat_cab_scale_idx"),
            models.Index(
                fields=["cabinet", "practice_area"],
                name="matters_mat_cabinet_70da90_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("cabinet", "reference"),
                condition=models.Q(is_deleted=False),
                name="uniq_matter_reference_per_cabinet",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference} — {self.title}"

    @property
    def is_treated(self) -> bool:
        """Dossier clos ou archivé — suppression interdite."""
        return self.status == MatterStatus.CLOSED or self.is_archived


class MatterSequence(TenantOwnedModel):
    """Séquence de numérotation des références de dossiers par année."""

    year = models.PositiveIntegerField(_("année"))
    last_number = models.PositiveIntegerField(_("dernier numéro"), default=0)

    class Meta:
        verbose_name = _("séquence dossier")
        verbose_name_plural = _("séquences dossiers")
        constraints = [
            models.UniqueConstraint(
                fields=("cabinet", "year"),
                condition=models.Q(is_deleted=False),
                name="uniq_matter_sequence_cabinet_year",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.cabinet_id}:{self.year}#{self.last_number}"


class MatterAction(TenantOwnedModel):
    """Entrée d'historique d'actions sur un dossier."""

    matter = models.ForeignKey(
        Matter,
        verbose_name=_("dossier"),
        on_delete=models.CASCADE,
        related_name="actions",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("auteur"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matter_actions",
    )
    action = models.CharField(_("action"), max_length=64)
    message = models.TextField(_("détail"), blank=True)

    class Meta:
        verbose_name = _("action dossier")
        verbose_name_plural = _("actions dossiers")
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.matter_id}:{self.action}"
