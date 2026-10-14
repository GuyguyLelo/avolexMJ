"""Services procurations : octroi ministériel et contrôle d'activité."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, BinaryIO

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile, File
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.procurations.models import Procuration, ProcurationSequence, ProcurationStatus
from apps.tenants.services import (
    can_finalize_procuration_act,
    can_issue_procuration,
    can_validate_as_conseiller,
    can_validate_as_dircaba,
    is_platform_admin,
    require_platform_admin,
)

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.matters.models import Matter
    from apps.tenants.models import Cabinet

PROCURATION_REQUIRED_MESSAGE = _(
    "Une procuration accordée par le Ministère de la Justice est obligatoire "
    "avant toute activité sur ce dossier."
)

PENDING_STATUSES = (
    ProcurationStatus.DRAFT,
    ProcurationStatus.REQUESTED,
    ProcurationStatus.APPROVED_CONSEILLER,
)
CONSEILLER_STATUSES = (ProcurationStatus.DRAFT, ProcurationStatus.REQUESTED)


def allocate_procuration_reference(*, cabinet: Cabinet, year: int | None = None) -> str:
    """Référence PROC-YYYY-NNNNN sous verrou."""
    year = year or timezone.localdate().year
    seq, _ = ProcurationSequence.objects.select_for_update().get_or_create(
        cabinet=cabinet,
        year=year,
        defaults={"last_number": 0},
    )
    seq.last_number += 1
    seq.save(update_fields=["last_number", "updated_at"])
    return f"PROC-{year}-{seq.last_number:05d}"


def valid_procurations_q(*, today: date | None = None) -> Q:
    """Filtre des procurations actuellement valides."""
    today = today or timezone.localdate()
    return (
        Q(status=ProcurationStatus.GRANTED)
        & (Q(expires_at__isnull=True) | Q(expires_at__gte=today))
        & (Q(valid_from__isnull=True) | Q(valid_from__lte=today))
    )


def _valid_procurations_for_matter(matter: Matter) -> QuerySet[Procuration]:
    """Procurations valides du dossier."""
    qs = Procuration.unscoped.filter(matter=matter).filter(valid_procurations_q())
    if matter.cabinet_id:
        qs = qs.filter(cabinet_id=matter.cabinet_id)
    return qs.select_related("granted_by")


def matter_has_valid_procuration(matter: Matter) -> bool:
    """Indique si le dossier est autorisé par une procuration en cours de validité."""
    return _valid_procurations_for_matter(matter).exists()


def get_valid_procuration(matter: Matter) -> Procuration | None:
    """Retourne la procuration valide du dossier, s'il y en a une."""
    return _valid_procurations_for_matter(matter).order_by("-granted_at", "-created_at").first()


def authorized_matter_ids_for_cabinet(*, cabinet: Cabinet) -> QuerySet[Any]:
    """Identifiants des dossiers que le cabinet peut consulter (procuration valide)."""
    return (
        Procuration.unscoped.filter(cabinet=cabinet, matter_id__isnull=False)
        .filter(valid_procurations_q())
        .values("matter_id")
    )


def require_valid_procuration(matter: Matter) -> Procuration:
    """Lève ValidationError si le dossier n'a pas de procuration ministérielle valide."""
    procuration = get_valid_procuration(matter)
    if procuration is None:
        raise ValidationError(PROCURATION_REQUIRED_MESSAGE)
    return procuration


def require_matter_activity_allowed(matter: Matter | None) -> None:
    """Bloque les actes de procédure tant que la procuration n'est pas accordée."""
    if matter is None:
        return
    require_valid_procuration(matter)


def stamp_granted_procuration(
    *,
    actor: User | None = None,
    cabinet: Cabinet | None = None,
    matter: Matter | None = None,
    subject: str = "",
    purpose: str = "",
    scale: str = "",
    jurisdiction: str = "",
    practice_area: str = "",
    client_name: str = "",
    ministry_reference: str = "",
    expires_at: date | None = None,
) -> Procuration:
    """Crée une procuration déjà accordée (démo, tests, seed)."""
    from apps.matters.models import MatterScale
    from apps.tenants.context import cabinet_context

    if matter is not None:
        cabinet = cabinet or matter.cabinet
        if cabinet is None:
            raise ValidationError(_("Un cabinet est obligatoire pour créer une procuration."))
        if matter.cabinet_id is None:
            from apps.matters.services import assign_matter_cabinet

            assign_matter_cabinet(matter=matter, cabinet=cabinet, actor=actor)
            matter.refresh_from_db()
        existing = get_valid_procuration(matter)
        if existing is not None:
            return existing
        subject = subject or matter.title
        scale = scale or matter.scale
        jurisdiction = jurisdiction or matter.jurisdiction
        practice_area = practice_area or matter.practice_area
    if cabinet is None:
        raise ValidationError(_("Un cabinet est obligatoire pour créer une procuration."))
    with cabinet_context(cabinet):
        today = timezone.localdate()
        procuration = Procuration(
            cabinet=cabinet,
            created_by=actor,
            matter=matter,
            subject=(subject or _("Affaire")).strip(),
            scale=scale or MatterScale.NATIONAL,
            jurisdiction=jurisdiction,
            practice_area=practice_area,
            client_name=client_name,
            reference=allocate_procuration_reference(cabinet=cabinet),
            purpose=(purpose or _("Représentation et actes de procédure")).strip(),
            status=ProcurationStatus.GRANTED,
            requested_at=today,
            granted_at=today,
            valid_from=today,
            expires_at=expires_at or (today + timedelta(days=365)),
            granted_by=actor,
            ministry_reference=(ministry_reference or "MJ-DEMO").strip(),
        )
        procuration.save()
        return procuration


RELATED_FIELDS = (
    "matter",
    "granted_by",
    "conseiller_by",
    "created_by",
    "cabinet",
)


def procurations_visible_qs(*, user: User, cabinet: Cabinet | None) -> QuerySet[Procuration]:
    """Queryset visible : cabinet courant, ou tous les cabinets pour le ministère."""
    if is_platform_admin(user):
        return Procuration.unscoped.select_related(*RELATED_FIELDS)
    if cabinet is None:
        return Procuration.objects.none()
    return Procuration.objects.filter(cabinet=cabinet).select_related(*RELATED_FIELDS)


def procurations_queryset(
    *,
    cabinet: Cabinet | None,
    q: str = "",
    status: str = "",
    matter_id: str = "",
    scale: str = "",
    cabinet_id: str = "",
    cross_cabinet: bool = False,
) -> QuerySet[Procuration]:
    """Liste filtrée des procurations (cabinet ou supervision)."""
    if cross_cabinet:
        qs = Procuration.unscoped.select_related(*RELATED_FIELDS)
    elif cabinet is not None:
        qs = Procuration.objects.filter(cabinet=cabinet).select_related(*RELATED_FIELDS)
    else:
        return Procuration.objects.none()
    q = (q or "").strip()
    if q:
        qs = qs.filter(
            Q(reference__icontains=q)
            | Q(ministry_reference__icontains=q)
            | Q(purpose__icontains=q)
            | Q(subject__icontains=q)
            | Q(client_name__icontains=q)
            | Q(matter__reference__icontains=q)
            | Q(matter__title__icontains=q)
            | Q(cabinet__name__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if matter_id:
        qs = qs.filter(matter_id=matter_id)
    if scale:
        qs = qs.filter(Q(scale=scale) | Q(matter__scale=scale))
    if cabinet_id:
        qs = qs.filter(cabinet_id=cabinet_id)
    return qs.order_by("-updated_at")


def _assert_unique_reference(
    *,
    cabinet: Cabinet,
    reference: str,
    exclude_pk: Any = None,
) -> None:
    qs = Procuration.unscoped.filter(cabinet=cabinet, reference=reference, is_deleted=False)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise ValidationError({"reference": _("Cette référence existe déjà pour ce cabinet.")})


def _resolve_reference(*, cabinet: Cabinet, reference: str = "") -> str:
    value = (reference or "").strip()
    if value:
        _assert_unique_reference(cabinet=cabinet, reference=value)
        return value
    return allocate_procuration_reference(cabinet=cabinet)


def _assert_matter_in_cabinet(*, matter: Matter, cabinet: Cabinet) -> None:
    """Autorise un dossier sans cabinet (avant procuration) ou déjà rattaché au même cabinet."""
    if matter.cabinet_id is None:
        return
    if matter.cabinet_id != cabinet.pk:
        raise PermissionDenied(_("Dossier inaccessible."))


def _assert_no_pending(*, matter: Matter | None, exclude_pk: Any = None) -> None:
    if matter is None:
        return
    qs = Procuration.unscoped.filter(matter=matter, status__in=PENDING_STATUSES)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise ValidationError(_("Une procuration est déjà en cours de délivrance pour ce dossier."))


def _assert_no_valid(*, matter: Matter | None, exclude_pk: Any = None) -> None:
    if matter is None:
        return
    qs = Procuration.unscoped.filter(matter=matter).filter(valid_procurations_q())
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    if qs.exists():
        raise ValidationError(
            _("Ce dossier dispose déjà d'une procuration ministérielle en cours de validité.")
        )


def _attach_instrument(*, procuration: Procuration, uploaded: File | None) -> None:
    if not uploaded:
        return
    name = getattr(uploaded, "name", "acte.pdf") or "acte.pdf"
    procuration.instrument = uploaded
    procuration.instrument_filename = str(name)[:255]


@transaction.atomic
def create_procuration(
    *,
    cabinet: Cabinet,
    user: User,
    matter: Matter,
    notes: str = "",
    instrument: File | BinaryIO | None = None,
    purpose: str = "Représentation et actes de procédure",
    ministry_reference: str = "",
    **_ignored: object,
) -> Procuration:
    """Le ministère ouvre une procuration (en attente validation Conseiller)."""
    return issue_procuration_for_validation(
        cabinet=cabinet,
        actor=user,
        matter=matter,
        purpose=purpose or "Représentation et actes de procédure",
        notes=notes,
        instrument=instrument,
        ministry_reference=ministry_reference,
    )


@transaction.atomic
def update_procuration(
    *,
    procuration: Procuration,
    user: User,
    notes: str | None = None,
    instrument: File | BinaryIO | None = None,
) -> Procuration:
    """Met à jour une procuration (réservé au ministère, données historiques)."""
    require_platform_admin(user)
    if procuration.status not in PENDING_STATUSES:
        raise ValidationError(_("Cette procuration ne peut plus être modifiée."))
    if notes is not None:
        procuration.notes = notes.strip()
    if instrument:
        _attach_instrument(procuration=procuration, uploaded=instrument)  # type: ignore[arg-type]
    procuration.save()
    return procuration


@transaction.atomic
def submit_procuration(*, procuration: Procuration, user: User) -> Procuration:
    """Transmet une ancienne demande brouillon (données historiques)."""
    require_platform_admin(user)
    if procuration.status != ProcurationStatus.DRAFT:
        raise ValidationError(_("Seule une procuration en brouillon peut être transmise."))
    _assert_no_valid(matter=procuration.matter, exclude_pk=procuration.pk)
    procuration.status = ProcurationStatus.REQUESTED
    procuration.requested_at = timezone.localdate()
    procuration.save(update_fields=["status", "requested_at", "updated_at"])
    return procuration


@transaction.atomic
def approve_by_conseiller(
    *,
    procuration: Procuration,
    actor: User,
    notes: str = "",
) -> Procuration:
    """1re validation : le Conseiller valide et transmet au Dircaba."""
    require_platform_admin(actor)
    if not can_validate_as_conseiller(actor):
        raise PermissionDenied(_("Réservé au Conseiller (1re validation)."))
    if procuration.status not in CONSEILLER_STATUSES:
        raise ValidationError(_("Cette procuration n'est pas en attente du Conseiller."))
    _assert_no_valid(matter=procuration.matter, exclude_pk=procuration.pk)
    today = timezone.localdate()
    if procuration.status == ProcurationStatus.DRAFT:
        procuration.requested_at = today
    procuration.status = ProcurationStatus.APPROVED_CONSEILLER
    procuration.conseiller_at = today
    procuration.conseiller_by = actor
    if notes:
        procuration.conseiller_notes = notes.strip()
    procuration.refused_at = None
    procuration.refusal_reason = ""
    procuration.save()
    return procuration


@transaction.atomic
def grant_procuration(
    *,
    procuration: Procuration,
    actor: User,
    ministry_reference: str = "",
    valid_from: date | None = None,
    expires_at: date | None = None,
    notes: str = "",
) -> Procuration:
    """2e validation : visa Dircaba — la procuration devient accordée."""
    require_platform_admin(actor)
    if not can_validate_as_dircaba(actor):
        raise PermissionDenied(_("Réservé au Dircaba (visa final)."))
    if procuration.status != ProcurationStatus.APPROVED_CONSEILLER:
        raise ValidationError(
            _("Le visa Dircaba n'est possible qu'après validation du Conseiller.")
        )
    _assert_no_valid(matter=procuration.matter, exclude_pk=procuration.pk)
    today = timezone.localdate()
    procuration.status = ProcurationStatus.GRANTED
    procuration.granted_at = today
    procuration.valid_from = valid_from or today
    procuration.expires_at = expires_at or (today + timedelta(days=365))
    procuration.granted_by = actor
    if ministry_reference:
        procuration.ministry_reference = ministry_reference.strip()
    if notes:
        procuration.notes = notes.strip()
    procuration.refused_at = None
    procuration.refusal_reason = ""
    procuration.save()
    return procuration


@transaction.atomic
def refuse_procuration(
    *,
    procuration: Procuration,
    actor: User,
    reason: str,
) -> Procuration:
    """Refuse une procuration en circuit de validation."""
    require_platform_admin(actor)
    if procuration.status not in PENDING_STATUSES:
        raise ValidationError(_("Seule une procuration en attente peut être refusée."))
    if procuration.awaits_conseiller and not can_validate_as_conseiller(actor):
        raise PermissionDenied(_("Réservé au Conseiller pour cette étape."))
    if procuration.awaits_dircaba and not can_validate_as_dircaba(actor):
        raise PermissionDenied(_("Réservé au Dircaba pour cette étape."))
    if not (reason or "").strip():
        raise ValidationError({"refusal_reason": _("Le motif du refus est obligatoire.")})
    procuration.status = ProcurationStatus.REFUSED
    procuration.refused_at = timezone.localdate()
    procuration.refusal_reason = reason.strip()
    procuration.save(update_fields=["status", "refused_at", "refusal_reason", "updated_at"])
    return procuration


@transaction.atomic
def revoke_procuration(
    *,
    procuration: Procuration,
    actor: User,
    reason: str,
) -> Procuration:
    """Révoque une procuration accordée (réservé au Ministère / supervision)."""
    require_platform_admin(actor)
    if procuration.status != ProcurationStatus.GRANTED:
        raise ValidationError(_("Seule une procuration accordée peut être révoquée."))
    if not (reason or "").strip():
        raise ValidationError({"revocation_reason": _("Le motif de révocation est obligatoire.")})
    procuration.status = ProcurationStatus.REVOKED
    procuration.revoked_at = timezone.localdate()
    procuration.revocation_reason = reason.strip()
    procuration.save(update_fields=["status", "revoked_at", "revocation_reason", "updated_at"])
    return procuration


@transaction.atomic
def soft_delete_procuration(*, procuration: Procuration, user: User) -> None:
    """Supprime une procuration non accordée (ministère uniquement)."""
    require_platform_admin(user)
    if procuration.status == ProcurationStatus.GRANTED and procuration.is_currently_valid:
        raise ValidationError(
            _("Une procuration accordée ne peut pas être supprimée. Le ministère doit la révoquer.")
        )
    procuration.soft_delete()


def issue_procuration_for_validation(
    *,
    cabinet: Cabinet,
    actor: User,
    purpose: str = "",
    subject: str = "",
    matter: Matter | None = None,
    scale: str = "",
    notes: str = "",
    reference: str = "",
    instrument: File | BinaryIO | None = None,
    ministry_reference: str = "",
    client_name: str = "",
) -> Procuration:
    """Ouvre une procuration en attente de double validation (Conseiller puis Dircaba)."""
    from apps.matters.models import MatterScale
    from apps.tenants.context import cabinet_context

    require_platform_admin(actor)
    if not can_issue_procuration(actor):
        raise PermissionDenied(
            _("Seule Synthia / l'administrateur peut créer une procuration.")
        )
    if matter is None:
        raise ValidationError({"matter": _("Le dossier est obligatoire.")})
    _assert_matter_in_cabinet(matter=matter, cabinet=cabinet)
    _assert_no_pending(matter=matter)
    _assert_no_valid(matter=matter)
    if not (purpose or "").strip():
        raise ValidationError({"purpose": _("L'objet de la procuration est obligatoire.")})
    subject = subject or matter.title
    scale = scale or matter.scale
    today = timezone.localdate()

    from apps.matters.services import assign_matter_cabinet

    assign_matter_cabinet(matter=matter, cabinet=cabinet, actor=actor)
    matter.refresh_from_db()

    with cabinet_context(cabinet):
        procuration = Procuration(
            cabinet=cabinet,
            created_by=actor,
            matter=matter,
            subject=subject.strip(),
            scale=scale or MatterScale.NATIONAL,
            jurisdiction=matter.jurisdiction or "",
            practice_area=matter.practice_area or "",
            client_name=client_name or "",
            reference=_resolve_reference(cabinet=cabinet, reference=reference),
            purpose=purpose.strip(),
            notes=notes.strip() if notes else "",
            status=ProcurationStatus.REQUESTED,
            requested_at=today,
            ministry_reference=(ministry_reference or "").strip(),
        )
        _attach_instrument(procuration=procuration, uploaded=instrument)  # type: ignore[arg-type]
        procuration.save()
        return procuration


# Compatibilité anciens appels / imports.
issue_granted_procuration = issue_procuration_for_validation


@transaction.atomic
def save_procuration_draft(
    *,
    procuration: Procuration,
    actor: User,
    html: str,
) -> Procuration:
    """Enregistre le brouillon HTML mis en forme (n'altère pas les champs métier)."""
    from apps.procurations.draft import sanitize_draft_html
    from apps.tenants.context import cabinet_context

    require_platform_admin(actor)
    if not can_finalize_procuration_act(actor):
        raise PermissionDenied(
            _("Seule Synthia / l'administrateur peut corriger l'acte après validation.")
        )
    if procuration.status != ProcurationStatus.GRANTED:
        raise ValidationError(
            _("L'acte ne peut être corrigé qu'après validation Conseiller et Dircaba.")
        )
    cleaned = sanitize_draft_html(html)
    if not cleaned:
        raise ValidationError(_("Le texte de l'acte ne peut pas être vide."))
    with cabinet_context(procuration.cabinet):
        procuration.draft_html = cleaned
        procuration.save(update_fields=["draft_html", "updated_at"])
    return procuration


@transaction.atomic
def reset_procuration_draft(*, procuration: Procuration, actor: User) -> Procuration:
    """Recharge le brouillon depuis les données métier (modèle officiel)."""
    from apps.procurations.draft import render_default_draft_html
    from apps.tenants.context import cabinet_context

    require_platform_admin(actor)
    if not can_finalize_procuration_act(actor):
        raise PermissionDenied(
            _("Seule Synthia / l'administrateur peut corriger l'acte après validation.")
        )
    if procuration.status != ProcurationStatus.GRANTED:
        raise ValidationError(
            _("L'acte ne peut être corrigé qu'après validation Conseiller et Dircaba.")
        )
    html = render_default_draft_html(procuration)
    with cabinet_context(procuration.cabinet):
        procuration.draft_html = html
        procuration.save(update_fields=["draft_html", "updated_at"])
    return procuration


@transaction.atomic
def generate_procuration_instrument(*, procuration: Procuration, actor: User) -> Procuration:
    """Publie l'acte PDF (après double validation — réservé à Synthia / admin)."""
    from apps.procurations.pdf import build_procuration_pdf
    from apps.tenants.context import cabinet_context

    require_platform_admin(actor)
    if not can_finalize_procuration_act(actor):
        raise PermissionDenied(
            _("Seule Synthia / l'administrateur peut publier l'acte après validation.")
        )
    if procuration.status != ProcurationStatus.GRANTED:
        raise ValidationError(
            _("L'acte ne peut être publié qu'après validation Conseiller et Dircaba.")
        )
    loaded = Procuration.unscoped.select_related(
        "cabinet", "matter", "granted_by"
    ).get(pk=procuration.pk)
    pdf_bytes = build_procuration_pdf(loaded)
    filename = f"{loaded.reference}.pdf"
    with cabinet_context(loaded.cabinet):
        if loaded.instrument:
            loaded.instrument.delete(save=False)
        _attach_instrument(
            procuration=loaded,
            uploaded=ContentFile(pdf_bytes, name=filename),
        )
        loaded.save(update_fields=["instrument", "instrument_filename", "updated_at"])
    return loaded
