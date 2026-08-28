"""Modèles des procurations délivrées par le Ministère de la Justice."""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantOwnedModel
from apps.matters.models import MatterScale
from apps.procurations.storage import private_procuration_storage


def procuration_upload_to(instance: Procuration, filename: str) -> str:
    """Chemin opaque cabinet/procuration/uuid.ext."""
    import uuid
    from pathlib import PurePosixPath

    ext = PurePosixPath(filename).suffix.lower()[:16]
    return f"{instance.cabinet_id}/{instance.pk}/{uuid.uuid4().hex}{ext}"


class ProcurationStatus(models.TextChoices):
    """Cycle de vie d'une procuration ministérielle."""

    DRAFT = "draft", _("Brouillon")
    REQUESTED = "requested", _("Demandée")
    GRANTED = "granted", _("Accordée")
    REFUSED = "refused", _("Refusée")
    REVOKED = "revoked", _("Révoquée")


class Procuration(TenantOwnedModel):
    """Autorisation délivrée par le Ministère de la Justice à un cabinet pour un dossier."""

    matter = models.ForeignKey(
        "matters.Matter",
        verbose_name=_("dossier"),
        on_delete=models.SET_NULL,
        related_name="procurations",
        null=True,
        blank=True,
        help_text=_("Dossier du cabinet auquel le ministère rattache cette procuration."),
    )
    subject = models.CharField(
        _("intitulé de l'affaire"),
        max_length=255,
        help_text=_("Intitulé recopié du dossier au moment de la délivrance."),
    )
    scale = models.CharField(
        _("échelle"),
        max_length=20,
        choices=MatterScale.choices,
        default=MatterScale.NATIONAL,
        db_index=True,
    )
    jurisdiction = models.CharField(_("juridiction"), max_length=255, blank=True)
    practice_area = models.CharField(_("matière / domaine"), max_length=120, blank=True)
    opposing_party = models.CharField(_("partie adverse"), max_length=255, blank=True)
    client_name = models.CharField(_("justiciable / client"), max_length=255, blank=True)
    reference = models.CharField(_("référence interne"), max_length=32, db_index=True)
    ministry_reference = models.CharField(
        _("référence ministérielle"),
        max_length=64,
        blank=True,
        help_text=_("Numéro porté sur l'acte du Ministère de la Justice."),
    )
    purpose = models.CharField(
        _("objet"),
        max_length=255,
        help_text=_("Objet de la procuration (représentation, actes de procédure…)."),
    )
    status = models.CharField(
        _("statut"),
        max_length=20,
        choices=ProcurationStatus.choices,
        default=ProcurationStatus.DRAFT,
        db_index=True,
    )
    requested_at = models.DateField(_("demandée le"), null=True, blank=True)
    granted_at = models.DateField(_("accordée le"), null=True, blank=True)
    valid_from = models.DateField(_("valide à compter du"), null=True, blank=True)
    expires_at = models.DateField(_("expire le"), null=True, blank=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("accordée par"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_procurations",
    )
    refused_at = models.DateField(_("refusée le"), null=True, blank=True)
    refusal_reason = models.TextField(_("motif du refus"), blank=True)
    revoked_at = models.DateField(_("révoquée le"), null=True, blank=True)
    revocation_reason = models.TextField(_("motif de révocation"), blank=True)
    notes = models.TextField(_("notes"), blank=True)
    instrument = models.FileField(
        _("acte scanné"),
        upload_to=procuration_upload_to,
        storage=private_procuration_storage,
        max_length=512,
        blank=True,
    )
    instrument_filename = models.CharField(_("nom du fichier"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("procuration")
        verbose_name_plural = _("procurations")
        ordering = ("-updated_at",)
        indexes = [
            models.Index(fields=["cabinet", "status"], name="proc_cab_status_idx"),
            models.Index(fields=["cabinet", "matter"], name="proc_cab_matter_idx"),
            models.Index(fields=["cabinet", "scale"], name="proc_cab_scale_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("cabinet", "reference"),
                condition=models.Q(is_deleted=False),
                name="uniq_procuration_reference_per_cabinet",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference} — {self.subject or self.purpose}"

    @property
    def case_title(self) -> str:
        """Intitulé affiché : dossier affecté, sinon affaire de la procuration."""
        if self.matter_id:
            return self.matter.title
        return self.subject

    @property
    def is_currently_valid(self) -> bool:
        """Accordée et encore dans sa période de validité."""
        if self.status != ProcurationStatus.GRANTED:
            return False
        today = timezone.localdate()
        if self.valid_from and self.valid_from > today:
            return False
        if self.expires_at and self.expires_at < today:
            return False
        return True

    @property
    def is_pending(self) -> bool:
        """Ancienne demande en attente (données historiques)."""
        return self.status in (ProcurationStatus.DRAFT, ProcurationStatus.REQUESTED)

    @property
    def is_editable(self) -> bool:
        """Les procurations ne sont plus modifiées par le cabinet."""
        return False

    @property
    def instrument_mime_type(self) -> str:
        """Type MIME de l'acte joint, d'après le nom de fichier."""
        import mimetypes

        name = self.instrument_filename
        if not name and self.instrument:
            name = self.instrument.name
        mime, _ = mimetypes.guess_type(name or "")
        if mime:
            return mime
        lower = (name or "").lower()
        if lower.endswith(".pdf"):
            return "application/pdf"
        if lower.endswith((".jpg", ".jpeg")):
            return "image/jpeg"
        if lower.endswith(".png"):
            return "image/png"
        if lower.endswith(".webp"):
            return "image/webp"
        if lower.endswith(".gif"):
            return "image/gif"
        return "application/octet-stream"

    @property
    def instrument_can_preview(self) -> bool:
        """Indique si l'acte joint peut être affiché (PDF ou image)."""
        from apps.documents.services import can_preview

        return bool(self.instrument) and can_preview(self.instrument_mime_type)


class ProcurationSequence(TenantOwnedModel):
    """Séquence de numérotation PROC-YYYY-NNNNN."""

    year = models.PositiveIntegerField(_("année"))
    last_number = models.PositiveIntegerField(_("dernier numéro"), default=0)

    class Meta:
        verbose_name = _("séquence procuration")
        verbose_name_plural = _("séquences procurations")
        constraints = [
            models.UniqueConstraint(
                fields=("cabinet", "year"),
                condition=models.Q(is_deleted=False),
                name="uniq_procuration_sequence_cabinet_year",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.cabinet_id}:{self.year}#{self.last_number}"
