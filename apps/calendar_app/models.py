"""Modèles agenda : événements et tâches."""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import PurePosixPath

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.calendar_app.storage import private_hearing_storage
from apps.core.models import TenantOwnedModel


def hearing_report_upload_to(instance: Event, filename: str) -> str:
    """Chemin opaque cabinet/audience/uuid.ext (champ legacy)."""
    ext = PurePosixPath(filename).suffix.lower()[:16]
    return f"{instance.cabinet_id}/{instance.pk}/{uuid.uuid4().hex}{ext}"


def hearing_attachment_upload_to(instance: HearingAttachment, filename: str) -> str:
    """Chemin opaque cabinet/audience/uuid.ext pour pièce jointe."""
    ext = PurePosixPath(filename).suffix.lower()[:16]
    event = instance.event
    return f"{event.cabinet_id}/{event.pk}/{uuid.uuid4().hex}{ext}"


class EventType(models.TextChoices):
    """Type d'événement agenda."""

    HEARING = "hearing", _("Audience")
    APPOINTMENT = "appointment", _("Rendez-vous")
    DEADLINE = "deadline", _("Délai de procédure")
    REMINDER = "reminder", _("Rappel")
    TASK = "task", _("Tâche")


class HearingStatus(models.TextChoices):
    """Statut d'une audience judiciaire."""

    SCHEDULED = "scheduled", _("Planifiée")
    HELD = "held", _("Tenue")
    POSTPONED = "postponed", _("Reportée")
    CANCELLED = "cancelled", _("Annulée")


def _guess_report_mime(name: str) -> str:
    mime, _ = mimetypes.guess_type(name or "")
    if mime:
        return mime
    lower = (name or "").lower()
    if lower.endswith(".pdf"):
        return "application/pdf"
    if lower.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lower.endswith(".doc"):
        return "application/msword"
    return "application/octet-stream"


class Event(TenantOwnedModel):
    """Événement / échéance / tâche du cabinet."""

    matter = models.ForeignKey(
        "matters.Matter",
        verbose_name=_("dossier"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="events",
    )
    event_type = models.CharField(
        _("type"),
        max_length=20,
        choices=EventType.choices,
        default=EventType.APPOINTMENT,
        db_index=True,
    )
    title = models.CharField(_("titre"), max_length=255)
    description = models.TextField(_("description"), blank=True)
    starts_at = models.DateTimeField(_("début"), db_index=True)
    ends_at = models.DateTimeField(_("fin"), null=True, blank=True)
    all_day = models.BooleanField(_("journée entière"), default=False)
    location = models.CharField(_("salle / lieu"), max_length=255, blank=True)
    court = models.CharField(_("tribunal"), max_length=255, blank=True)
    chamber = models.CharField(_("chambre"), max_length=128, blank=True)
    hearing_status = models.CharField(
        _("statut audience"),
        max_length=20,
        choices=HearingStatus.choices,
        blank=True,
        default="",
        db_index=True,
    )
    hearing_report = models.TextField(_("compte-rendu d'audience"), blank=True)
    hearing_report_file = models.FileField(
        _("rapport d'audience (legacy)"),
        upload_to=hearing_report_upload_to,
        storage=private_hearing_storage,
        max_length=512,
        blank=True,
    )
    hearing_report_filename = models.CharField(_("nom du rapport"), max_length=255, blank=True)
    is_done = models.BooleanField(_("terminé"), default=False)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("assigné à"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_events",
    )
    remind_at = models.DateTimeField(
        _("rappel le"),
        null=True,
        blank=True,
        db_index=True,
        help_text=_("Date/heure d'envoi du rappel e-mail."),
    )
    reminder_sent_at = models.DateTimeField(_("rappel envoyé le"), null=True, blank=True)

    class Meta:
        verbose_name = _("Événement")
        verbose_name_plural = _("Événements")
        ordering = ("starts_at",)
        indexes = [
            models.Index(fields=["cabinet", "starts_at"], name="calendar_ap_cabinet_7be077_idx"),
            models.Index(
                fields=["cabinet", "event_type", "hearing_status", "starts_at"],
                name="cal_event_hearing_status_idx",
            ),
            models.Index(
                fields=["remind_at"],
                name="cal_event_remind_pending_idx",
                condition=models.Q(is_deleted=False, reminder_sent_at__isnull=True),
            ),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def has_hearing_report(self) -> bool:
        """Indique si au moins un fichier ou un compte-rendu texte est présent."""
        if self.pk and self.attachments.exists():
            return True
        return bool(self.hearing_report_file) or bool(self.hearing_report.strip())

    @property
    def hearing_report_mime_type(self) -> str:
        """Type MIME du rapport legacy, d'après le nom de fichier."""
        name = self.hearing_report_filename
        if not name and self.hearing_report_file:
            name = self.hearing_report_file.name
        return _guess_report_mime(name)

    @property
    def hearing_report_can_preview(self) -> bool:
        """Le PDF peut s'afficher dans le navigateur ; Word se télécharge."""
        return bool(self.hearing_report_file) and self.hearing_report_mime_type == "application/pdf"


class HearingAttachment(models.Model):
    """Fichier joint à une audience (plusieurs possibles)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(
        Event,
        verbose_name=_("audience"),
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(
        _("fichier"),
        upload_to=hearing_attachment_upload_to,
        storage=private_hearing_storage,
        max_length=512,
    )
    original_filename = models.CharField(_("nom du fichier"), max_length=255)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("déposé par"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hearing_attachments_uploaded",
    )
    created_at = models.DateTimeField(_("créé le"), auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("Pièce jointe d'audience")
        verbose_name_plural = _("Pièces jointes d'audience")
        ordering = ("created_at",)

    def __str__(self) -> str:
        return self.original_filename

    @property
    def mime_type(self) -> str:
        """Type MIME d'après le nom de fichier."""
        return _guess_report_mime(self.original_filename or (self.file.name if self.file else ""))

    @property
    def can_preview(self) -> bool:
        """Aperçu navigateur réservé aux PDF."""
        return self.mime_type == "application/pdf"
