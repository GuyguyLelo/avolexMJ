"""Modèles dossiers (socle requis par la GED)."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantOwnedModel
from apps.core.managers import SoftDeleteManager


class MatterStatus(models.TextChoices):
    """Statut d'un dossier."""

    OPEN = "open", _("Ouvert (En introduction)")
    IN_PROGRESS = "in_progress", _("En cours")
    ON_HOLD = "on_hold", _("En attente")
    CLOSED = "closed", _("Clos")


class MatterScale(models.TextChoices):
    """Échelle de traitement par le Ministère de la Justice."""

    NATIONAL = "national", _("Nationale")
    INTERNATIONAL = "international", _("Internationale")


class PartyRole(models.TextChoices):
    """Rôle d'une partie dans un dossier."""

    PLAINTIFF = "plaintiff", _("Plaignant / Accusateur")
    DEFENDANT = "defendant", _("Défendeur / Accusé")
    WITNESS = "witness", _("Témoin")
    THIRD_PARTY = "third_party", _("Tiers")


class Matter(TenantOwnedModel):
    """Dossier / affaire. Le cabinet n'est rattaché qu'à la délivrance de la procuration."""

    cabinet = models.ForeignKey(
        "tenants.Cabinet",
        verbose_name=_("cabinet"),
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_set",
        db_index=True,
        null=True,
        blank=True,
        help_text=_("Rattaché lors de la délivrance de la procuration ministérielle."),
    )
    reference = models.CharField(_("référence"), max_length=32, db_index=True)
    title = models.CharField(_("intitulé"), max_length=255)
    description = models.TextField(_("description"), blank=True)
    practice_area = models.CharField(_("matière / domaine"), max_length=120, blank=True)
    jurisdiction = models.CharField(_("juridiction"), max_length=255, blank=True)
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
    responsible_lawyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("avocat responsable"),
        on_delete=models.PROTECT,
        related_name="responsible_matters",
        null=True,
        blank=True,
        help_text=_("Désigné lors du rattachement du cabinet (procuration)."),
    )
    opened_at = models.DateField(_("ouvert le"), null=True, blank=True)
    closed_at = models.DateField(_("clos le"), null=True, blank=True)
    is_archived = models.BooleanField(_("archivé"), default=False, db_index=True)
    notes = models.TextField(_("notes"), blank=True)
    initial_pdf = models.FileField(_("Dossier scanné"), upload_to="matters/%Y/%m/", blank=True, null=True)
    search_vector = SearchVectorField(_("vecteur de recherche"), null=True, editable=False)

    class Meta:
        verbose_name = _("Dossier")
        verbose_name_plural = _("Dossiers")
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
                fields=("reference",),
                condition=models.Q(is_deleted=False),
                name="uniq_matter_reference_alive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference} — {self.title}"

    def save(self, *args: object, **kwargs: object) -> None:
        """N'assigne pas automatiquement un cabinet (réservé à la procuration)."""
        # Skip TenantOwnedModel.save (auto-cabinet depuis le contexte).
        super(TenantOwnedModel, self).save(*args, **kwargs)

    @property
    def is_treated(self) -> bool:
        """Dossier clos ou archivé — suppression interdite."""
        return self.status == MatterStatus.CLOSED or self.is_archived


class MatterLawyer(models.Model):
    """Avocat du cabinet affecté à un dossier (un ou plusieurs)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    matter = models.ForeignKey(
        Matter,
        verbose_name=_("dossier"),
        on_delete=models.CASCADE,
        related_name="assigned_lawyers",
    )
    lawyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("avocat"),
        on_delete=models.CASCADE,
        related_name="matter_assignments",
    )
    is_lead = models.BooleanField(
        _("avocat responsable"),
        default=False,
        help_text=_("Avocat principal du dossier."),
    )
    assigned_at = models.DateTimeField(_("affecté le"), auto_now_add=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("affecté par"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matter_lawyer_assignments_made",
    )

    class Meta:
        verbose_name = _("Avocat du dossier")
        verbose_name_plural = _("Avocats du dossier")
        ordering = ("-is_lead", "assigned_at")
        constraints = [
            models.UniqueConstraint(
                fields=("matter", "lawyer"),
                name="uniq_matter_lawyer_assignment",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.matter_id}:{self.lawyer_id}"


class MatterParty(TenantOwnedModel):
    """Partie impliquée dans un dossier avec son rôle."""

    objects = SoftDeleteManager()
    unscoped = SoftDeleteManager()

    cabinet = models.ForeignKey(
        "tenants.Cabinet",
        verbose_name=_("cabinet"),
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_set",
        db_index=True,
        null=True,
        blank=True,
    )
    matter = models.ForeignKey(
        Matter,
        verbose_name=_("dossier"),
        on_delete=models.CASCADE,
        related_name="parties",
    )
    name = models.CharField(_("nom de la partie"), max_length=255)
    role = models.CharField(
        _("rôle"),
        max_length=20,
        choices=PartyRole.choices,
        default=PartyRole.DEFENDANT,
    )
    is_state_entity = models.BooleanField(
        _("entité étatique"),
        default=False,
        help_text=_("Indique si cette partie est un service de l'État congolais"),
    )
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        verbose_name = _("Partie")
        verbose_name_plural = _("Parties")
        ordering = ("role", "name")

    def save(self, *args: object, **kwargs: object) -> None:
        if self.cabinet_id is None and self.matter_id and self.matter.cabinet_id:
            self.cabinet_id = self.matter.cabinet_id
        super(TenantOwnedModel, self).save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.get_role_display})"


class MatterSequence(TenantOwnedModel):
    """Séquence de numérotation des références de dossiers par année (par cabinet)."""

    year = models.PositiveIntegerField(_("année"))
    last_number = models.PositiveIntegerField(_("dernier numéro"), default=0)

    class Meta:
        verbose_name = _("Séquence dossier")
        verbose_name_plural = _("Séquences dossiers")
        constraints = [
            models.UniqueConstraint(
                fields=("cabinet", "year"),
                condition=models.Q(is_deleted=False),
                name="uniq_matter_sequence_cabinet_year",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.cabinet_id}:{self.year}#{self.last_number}"


class MatterGlobalSequence(models.Model):
    """Numérotation ministérielle des dossiers (avant rattachement cabinet)."""

    year = models.PositiveIntegerField(_("année"), unique=True)
    last_number = models.PositiveIntegerField(_("dernier numéro"), default=0)

    class Meta:
        verbose_name = _("Séquence dossier ministère")
        verbose_name_plural = _("Séquences dossiers ministère")

    def __str__(self) -> str:
        return f"MJ:{self.year}#{self.last_number}"


class MatterAction(TenantOwnedModel):
    """Entrée d'historique d'actions sur un dossier."""

    objects = SoftDeleteManager()
    unscoped = SoftDeleteManager()

    cabinet = models.ForeignKey(
        "tenants.Cabinet",
        verbose_name=_("cabinet"),
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_set",
        db_index=True,
        null=True,
        blank=True,
    )
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
        verbose_name = _("Action dossier")
        verbose_name_plural = _("Actions dossiers")
        ordering = ("-created_at",)

    def save(self, *args: object, **kwargs: object) -> None:
        if self.cabinet_id is None and self.matter_id and self.matter.cabinet_id:
            self.cabinet_id = self.matter.cabinet_id
        super(TenantOwnedModel, self).save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.matter_id}:{self.action}"
