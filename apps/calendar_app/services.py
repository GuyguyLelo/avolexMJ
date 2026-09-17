"""Services agenda."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.calendar_app.models import Event, EventType, HearingAttachment, HearingStatus
from apps.documents.services import get_max_upload_bytes
from apps.tenants.roles import PERM_ADD, PERM_CHANGE, PERM_DELETE
from apps.tenants.services import require_cabinet_perm

if TYPE_CHECKING:
    from django.core.files import File

    from apps.accounts.models import User
    from apps.matters.models import Matter
    from apps.tenants.models import Cabinet

REPORT_ALLOWED_EXTENSIONS = frozenset({".pdf", ".doc", ".docx"})
REPORT_ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/msword",
        "application/vnd.ms-word",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    }
)


def events_queryset(
    *,
    cabinet: Cabinet,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    event_type: str = "",
    matter_id: str = "",
) -> QuerySet[Event]:
    """Événements filtrés."""
    qs = Event.objects.filter(cabinet=cabinet).select_related("matter", "assigned_to")
    if from_dt:
        qs = qs.filter(starts_at__gte=from_dt)
    if to_dt:
        qs = qs.filter(starts_at__lte=to_dt)
    if event_type:
        qs = qs.filter(event_type=event_type)
    if matter_id:
        qs = qs.filter(matter_id=matter_id)
    return qs.order_by("starts_at")


def hearings_queryset(
    *,
    cabinet: Cabinet | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    matter_id: str = "",
    hearing_status: str = "",
    court: str = "",
    cabinet_id: str = "",
    upcoming_only: bool = False,
    cross_cabinet: bool = False,
) -> QuerySet[Event]:
    """Audiences judiciaires filtrées (cabinet ou supervision nationale)."""
    related = ("matter", "assigned_to", "matter__responsible_lawyer", "matter__cabinet", "cabinet")
    if cross_cabinet:
        qs = Event.unscoped.filter(event_type=EventType.HEARING).select_related(*related)
    elif cabinet is not None:
        qs = (
            Event.objects.filter(cabinet=cabinet, event_type=EventType.HEARING)
            .select_related(*related)
        )
    else:
        return Event.objects.none()
    if from_dt:
        qs = qs.filter(starts_at__gte=from_dt)
    if to_dt:
        qs = qs.filter(starts_at__lte=to_dt)
    if matter_id:
        qs = qs.filter(matter_id=matter_id)
    if hearing_status:
        qs = qs.filter(hearing_status=hearing_status)
    if court:
        qs = qs.filter(court=court)
    if cabinet_id:
        qs = qs.filter(cabinet_id=cabinet_id)
    if upcoming_only:
        qs = qs.filter(
            starts_at__gte=timezone.now() - timedelta(days=1),
            hearing_status__in=(HearingStatus.SCHEDULED, ""),
        )
    return qs.order_by("starts_at")


def _clear_hearing_fields() -> dict[str, str]:
    return {
        "court": "",
        "chamber": "",
        "hearing_status": "",
        "hearing_report": "",
        "hearing_report_filename": "",
        "hearing_report_file": "",
    }


def validate_hearing_report_file(uploaded: File) -> None:
    """Autorise uniquement PDF, DOC et DOCX, dans la limite de taille GED."""
    name = getattr(uploaded, "name", "") or ""
    ext = PurePosixPath(name).suffix.lower()
    if ext not in REPORT_ALLOWED_EXTENSIONS:
        raise ValidationError(_("Le rapport doit être un fichier PDF, DOC ou DOCX."))
    mime = (getattr(uploaded, "content_type", None) or "").split(";")[0].strip().lower()
    if mime and mime not in REPORT_ALLOWED_MIME_TYPES:
        raise ValidationError(_("Le rapport doit être un fichier PDF, DOC ou DOCX."))
    size = getattr(uploaded, "size", None)
    max_bytes = get_max_upload_bytes()
    if size is not None and size <= 0:
        raise ValidationError(_("Fichier vide."))
    if size is not None and size > max_bytes:
        raise ValidationError(
            _("Fichier trop volumineux (max %(max)s Mo).")
            % {"max": max_bytes // (1024 * 1024)}
        )


def _attach_hearing_report(*, event: Event, uploaded: File, user: User | None = None) -> HearingAttachment:
    """Ajoute une pièce jointe (n'écrase pas les fichiers existants)."""
    validate_hearing_report_file(uploaded)
    name = getattr(uploaded, "name", "rapport.pdf") or "rapport.pdf"
    attachment = HearingAttachment(
        event=event,
        original_filename=str(name)[:255],
        uploaded_by=user,
    )
    attachment.file = uploaded
    attachment.save()
    event.hearing_report = ""
    event.save(update_fields=["hearing_report", "updated_at"])
    return attachment


@transaction.atomic
def create_event(
    *,
    cabinet: Cabinet,
    user: User,
    title: str,
    starts_at: datetime,
    event_type: str = EventType.APPOINTMENT,
    matter: Matter | None = None,
    description: str = "",
    ends_at: datetime | None = None,
    all_day: bool = False,
    location: str = "",
    court: str = "",
    chamber: str = "",
    hearing_status: str = "",
    hearing_report: str = "",
    assigned_to: User | None = None,
    remind_at: datetime | None = None,
) -> Event:
    """Crée un événement / tâche."""
    require_cabinet_perm(user=user, cabinet=cabinet, perm=PERM_ADD)
    if matter is not None and matter.cabinet_id != cabinet.pk:
        raise PermissionDenied(_("Dossier inaccessible."))
    if matter is not None:
        from apps.procurations.services import require_matter_activity_allowed

        require_matter_activity_allowed(matter)
    if not title.strip():
        raise ValidationError({"title": _("Le titre est obligatoire.")})
    hearing_data: dict[str, Any] = {}
    if event_type == EventType.HEARING:
        if matter is not None:
            court = (matter.jurisdiction or "").strip() or court
        hearing_data = {
            "court": court,
            "chamber": chamber,
            "hearing_status": hearing_status or HearingStatus.SCHEDULED,
            "hearing_report": hearing_report,
        }
    return Event.objects.create(
        cabinet=cabinet,
        created_by=user,
        matter=matter,
        event_type=event_type,
        title=title.strip(),
        description=description,
        starts_at=starts_at,
        ends_at=ends_at,
        all_day=all_day,
        location=location,
        assigned_to=assigned_to or user,
        remind_at=remind_at,
        **hearing_data,
    )


@transaction.atomic
def update_event(*, event: Event, user: User, **fields: Any) -> Event:
    """Met à jour un événement."""
    require_cabinet_perm(user=user, cabinet=event.cabinet, perm=PERM_CHANGE)
    matter = fields.get("matter", event.matter)
    if matter is not None:
        from apps.procurations.services import require_matter_activity_allowed

        require_matter_activity_allowed(matter)
    event_type = fields.get("event_type", event.event_type)
    if event_type != EventType.HEARING:
        if event.hearing_report_file:
            event.hearing_report_file.delete(save=False)
        for attachment in list(event.attachments.all()):
            if attachment.file:
                attachment.file.delete(save=False)
            attachment.delete()
        fields = {**fields, **_clear_hearing_fields()}
    else:
        if not fields.get("hearing_status") and not event.hearing_status:
            fields["hearing_status"] = HearingStatus.SCHEDULED
        linked_matter = fields.get("matter", event.matter)
        if linked_matter is not None:
            fields["court"] = (getattr(linked_matter, "jurisdiction", None) or "").strip()
        elif "matter" in fields and fields["matter"] is None:
            fields["court"] = ""
    fields.pop("report_file", None)
    for key, value in fields.items():
        setattr(event, key, value)
    event.save()
    return event


@transaction.atomic
def update_hearing_status(
    *,
    event: Event,
    user: User,
    hearing_status: str,
    hearing_report: str = "",
) -> Event:
    """Met à jour le statut d'une audience."""
    require_cabinet_perm(user=user, cabinet=event.cabinet, perm=PERM_CHANGE)
    if event.matter_id:
        from apps.procurations.services import require_matter_activity_allowed

        require_matter_activity_allowed(event.matter)
    if event.event_type != EventType.HEARING:
        raise ValidationError(_("Cet événement n'est pas une audience."))
    if hearing_status not in HearingStatus.values:
        raise ValidationError(_("Statut d'audience invalide."))
    event.hearing_status = hearing_status
    if hearing_report:
        event.hearing_report = hearing_report
    if hearing_status == HearingStatus.HELD:
        event.is_done = True
    event.save(update_fields=["hearing_status", "hearing_report", "is_done", "updated_at"])
    return event


@transaction.atomic
def save_hearing_report(
    *,
    event: Event,
    user: User,
    uploaded: File | None = None,
    uploads: list[File] | None = None,
    mark_held: bool = False,
) -> Event:
    """Joint un ou plusieurs fichiers Word/PDF à l'audience."""
    require_cabinet_perm(user=user, cabinet=event.cabinet, perm=PERM_CHANGE)
    if event.event_type != EventType.HEARING:
        raise ValidationError(_("Cet événement n'est pas une audience."))
    if event.matter_id:
        from apps.procurations.services import require_matter_activity_allowed

        require_matter_activity_allowed(event.matter)
    files: list[File] = list(uploads or [])
    if uploaded is not None:
        files.append(uploaded)
    if not files and not event.attachments.exists() and not event.hearing_report_file:
        raise ValidationError(_("Joignez au moins un fichier Word ou PDF."))
    for item in files:
        _attach_hearing_report(event=event, uploaded=item, user=user)
    if mark_held:
        event.hearing_status = HearingStatus.HELD
        event.is_done = True
        event.save(update_fields=["hearing_status", "is_done", "updated_at"])
    return event


@transaction.atomic
def delete_hearing_attachment(*, attachment: HearingAttachment, user: User) -> None:
    """Supprime une pièce jointe d'audience."""
    event = attachment.event
    require_cabinet_perm(user=user, cabinet=event.cabinet, perm=PERM_CHANGE)
    if attachment.file:
        attachment.file.delete(save=False)
    attachment.delete()


@transaction.atomic
def mark_event_done(*, event: Event, user: User, done: bool = True) -> Event:
    """Marque une tâche comme terminée."""
    require_cabinet_perm(user=user, cabinet=event.cabinet, perm=PERM_CHANGE)
    event.is_done = done
    event.save(update_fields=["is_done", "updated_at"])
    return event


@transaction.atomic
def soft_delete_event(*, event: Event, user: User) -> None:
    """Suppression logique."""
    require_cabinet_perm(user=user, cabinet=event.cabinet, perm=PERM_DELETE)
    event.soft_delete()


def pending_reminders(*, now: datetime | None = None) -> QuerySet[Event]:
    """Événements dont le rappel est dû."""
    now = now or timezone.now()
    return Event.unscoped.filter(
        is_deleted=False,
        remind_at__isnull=False,
        remind_at__lte=now,
        reminder_sent_at__isnull=True,
    ).select_related("cabinet", "assigned_to", "matter")
