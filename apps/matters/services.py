"""Services dossiers : numérotation, CRUD, historique, recherche."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from django.contrib.postgres.search import SearchVector
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.kinshasa_courts import international_court_values, national_court_values
from apps.matters.models import Matter, MatterAction, MatterScale, MatterSequence, MatterStatus
from apps.tenants.context import cabinet_context
from apps.tenants.roles import PERM_CHANGE, PERM_DELETE
from apps.tenants.services import is_platform_admin, require_cabinet_perm

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.clients.models import Client
    from apps.tenants.models import Cabinet


def log_matter_action(
    *,
    matter: Matter,
    user: User | None,
    action: str,
    message: str = "",
) -> MatterAction:
    """Enregistre une entrée d'historique."""
    return MatterAction.objects.create(
        cabinet=matter.cabinet,
        matter=matter,
        actor=user,
        action=action,
        message=message,
        created_by=user,
    )


@transaction.atomic
def allocate_matter_reference(*, cabinet: Cabinet, year: int | None = None) -> str:
    """Référence DOS-YYYY-NNNNN sous verrou."""
    year = year or timezone.localdate().year
    seq, _ = MatterSequence.objects.select_for_update().get_or_create(
        cabinet=cabinet,
        year=year,
        defaults={"last_number": 0},
    )
    seq.last_number += 1
    seq.save(update_fields=["last_number", "updated_at"])
    return f"DOS-{year}-{seq.last_number:05d}"


def refresh_matter_search_vector(matter: Matter) -> None:
    """Met à jour le vecteur FTS."""
    Matter.objects.filter(pk=matter.pk).update(
        search_vector=(
            SearchVector("reference", weight="A", config="french")
            + SearchVector("title", weight="A", config="french")
            + SearchVector("description", weight="B", config="french")
            + SearchVector("practice_area", weight="B", config="french")
            + SearchVector("jurisdiction", weight="B", config="french")
            + SearchVector("opposing_party", weight="C", config="french")
        )
    )


def matters_queryset(
    *,
    cabinet: Cabinet,
    q: str = "",
    status: str = "",
    client_id: str = "",
    archived: str = "",
    scale: str = "",
    user: User | None = None,
) -> QuerySet[Matter]:
    """Liste filtrée des dossiers. Un cabinet ne voit que ceux avec procuration valide."""
    qs = Matter.objects.filter(cabinet=cabinet).select_related(
        "client",
        "responsible_lawyer",
    )
    if user is not None and not is_platform_admin(user):
        from apps.procurations.services import authorized_matter_ids_for_cabinet

        qs = qs.filter(pk__in=authorized_matter_ids_for_cabinet(cabinet=cabinet))
    archived_filter = (archived or "").strip().lower()
    if archived_filter == "1" or archived_filter == "true":
        qs = qs.filter(is_archived=True)
    elif archived_filter == "all":
        pass
    else:
        qs = qs.filter(is_archived=False)
    q = (q or "").strip()
    if q:
        qs = qs.filter(
            Q(reference__icontains=q)
            | Q(title__icontains=q)
            | Q(practice_area__icontains=q)
            | Q(opposing_party__icontains=q)
            | Q(jurisdiction__icontains=q)
            | Q(client__last_name__icontains=q)
            | Q(client__company_name__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if client_id:
        qs = qs.filter(client_id=client_id)
    if scale:
        qs = qs.filter(scale=scale)
    return qs.order_by("-updated_at")


def validate_matter_scale(*, scale: str, jurisdiction: str) -> None:
    """Refuse une juridiction dont l'échelle ne correspond pas."""
    scale = scale or MatterScale.NATIONAL
    court = (jurisdiction or "").strip()
    if not court:
        return
    if scale == MatterScale.NATIONAL and court in international_court_values():
        raise ValidationError(
            {
                "jurisdiction": _(
                    "Cette juridiction est internationale. Choisissez l'échelle internationale."
                )
            }
        )
    if scale == MatterScale.INTERNATIONAL and court in national_court_values():
        raise ValidationError(
            {"jurisdiction": _("Cette juridiction est nationale. Choisissez l'échelle nationale.")}
        )


@transaction.atomic
def create_matter(
    *,
    cabinet: Cabinet,
    user: User,
    client: Client,
    title: str,
    responsible_lawyer: User,
    description: str = "",
    practice_area: str = "",
    jurisdiction: str = "",
    opposing_party: str = "",
    scale: str = MatterScale.NATIONAL,
    status: str = MatterStatus.OPEN,
    opened_at: date | None = None,
    closed_at: date | None = None,
    notes: str = "",
) -> Matter:
    """Crée un dossier : réservé au Ministère de la Justice."""
    if not is_platform_admin(user):
        raise PermissionDenied(_("Seul le Ministère de la Justice peut ouvrir un dossier."))
    if client.cabinet_id != cabinet.pk:
        raise PermissionDenied(_("Client inaccessible."))
    if not title.strip():
        raise ValidationError({"title": _("L'intitulé est obligatoire.")})
    scale = scale or MatterScale.NATIONAL
    validate_matter_scale(scale=scale, jurisdiction=jurisdiction)
    with cabinet_context(cabinet):
        matter = Matter.objects.create(
            cabinet=cabinet,
            created_by=user,
            client=client,
            responsible_lawyer=responsible_lawyer,
            reference=allocate_matter_reference(cabinet=cabinet),
            title=title.strip(),
            description=description,
            practice_area=practice_area,
            jurisdiction=jurisdiction,
            opposing_party=opposing_party,
            scale=scale,
            status=status,
            opened_at=opened_at or timezone.localdate(),
            closed_at=closed_at,
            notes=notes,
        )
        refresh_matter_search_vector(matter)
        log_matter_action(
            matter=matter,
            user=user,
            action="created",
            message=_("Dossier créé."),
        )
        return matter


@transaction.atomic
def update_matter(*, matter: Matter, user: User, **fields: Any) -> Matter:
    """Met à jour un dossier et journalise les changements de statut."""
    require_cabinet_perm(user=user, cabinet=matter.cabinet, perm=PERM_CHANGE)
    fields.pop("target_cabinet", None)
    old_status = matter.status
    incoming_status = fields.get("status", matter.status)
    if incoming_status == MatterStatus.IN_PROGRESS:
        from apps.procurations.services import require_valid_procuration

        require_valid_procuration(matter)
    if "client" in fields and fields["client"].cabinet_id != matter.cabinet_id:
        raise PermissionDenied(_("Client inaccessible."))
    for key, value in fields.items():
        setattr(matter, key, value)
    validate_matter_scale(scale=matter.scale, jurisdiction=matter.jurisdiction)
    if matter.status == MatterStatus.CLOSED and matter.closed_at is None:
        matter.closed_at = timezone.localdate()
    matter.save()
    refresh_matter_search_vector(matter)
    if old_status != matter.status:
        log_matter_action(
            matter=matter,
            user=user,
            action="status_changed",
            message=f"{old_status} → {matter.status}",
        )
    else:
        log_matter_action(
            matter=matter,
            user=user,
            action="updated",
            message=_("Dossier modifié."),
        )
    return matter


@transaction.atomic
def archive_matter(*, matter: Matter, user: User) -> Matter:
    """Archive un dossier clos pour consultation ultérieure."""
    require_cabinet_perm(user=user, cabinet=matter.cabinet, perm=PERM_CHANGE)
    if matter.is_archived:
        return matter
    if matter.status != MatterStatus.CLOSED:
        raise ValidationError(_("Seuls les dossiers clos peuvent être archivés."))
    matter.is_archived = True
    matter.save(update_fields=["is_archived", "updated_at"])
    log_matter_action(
        matter=matter,
        user=user,
        action="archived",
        message=_("Dossier archivé."),
    )
    return matter


@transaction.atomic
def soft_delete_matter(*, matter: Matter, user: User) -> None:
    """Suppression logique — interdite pour les dossiers traités."""
    require_cabinet_perm(user=user, cabinet=matter.cabinet, perm=PERM_DELETE)
    if matter.is_treated:
        raise ValidationError(
            _(
                "Un dossier clos ou archivé ne peut pas être supprimé. "
                "Archivez-le pour consultation."
            )
        )
    log_matter_action(
        matter=matter,
        user=user,
        action="deleted",
        message=_("Dossier supprimé."),
    )
    matter.soft_delete()
