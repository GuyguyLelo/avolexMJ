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

from apps.tenants.jurisdictions import international_jurisdiction_names, national_jurisdiction_names
from apps.matters.models import (
    Matter,
    MatterAction,
    MatterLawyer,
    MatterScale,
    MatterSequence,
    MatterStatus,
)
from apps.tenants.services import is_platform_admin

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.tenants.models import Cabinet


def log_matter_action(
    *,
    matter: Matter,
    user: User | None,
    action: str,
    message: str = "",
) -> MatterAction:
    """Enregistre une entrée d'historique."""
    return MatterAction.unscoped.create(
        cabinet=matter.cabinet,
        matter=matter,
        actor=user,
        action=action,
        message=message,
        created_by=user,
    )


@transaction.atomic
def allocate_matter_reference(*, cabinet: Cabinet | None = None, year: int | None = None) -> str:
    """Référence DOS-YYYY-NNNNN sous verrou (ministère ou par cabinet)."""
    from apps.matters.models import MatterGlobalSequence

    year = year or timezone.localdate().year
    if cabinet is None:
        seq, _ = MatterGlobalSequence.objects.select_for_update().get_or_create(
            year=year,
            defaults={"last_number": 0},
        )
        seq.last_number += 1
        seq.save(update_fields=["last_number"])
        return f"DOS-{year}-{seq.last_number:05d}"

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
    Matter.unscoped.filter(pk=matter.pk).update(
        search_vector=(
            SearchVector("reference", weight="A", config="french")
            + SearchVector("title", weight="A", config="french")
            + SearchVector("description", weight="B", config="french")
            + SearchVector("practice_area", weight="B", config="french")
            + SearchVector("jurisdiction", weight="B", config="french")
        )
    )


def matters_queryset(
    *,
    cabinet: Cabinet | None,
    q: str = "",
    status: str = "",
    archived: str = "",
    scale: str = "",
    user: User | None = None,
) -> QuerySet[Matter]:
    """Liste filtrée des dossiers. Un cabinet ne voit que ceux avec procuration valide."""
    if user is not None and is_platform_admin(user):
        qs = Matter.unscoped.all().select_related("responsible_lawyer", "cabinet")
    elif cabinet is not None:
        qs = Matter.unscoped.filter(cabinet=cabinet).select_related(
            "responsible_lawyer",
            "cabinet",
        )
        if user is not None:
            from apps.procurations.services import authorized_matter_ids_for_cabinet

            qs = qs.filter(pk__in=authorized_matter_ids_for_cabinet(cabinet=cabinet))
    else:
        qs = Matter.unscoped.none()
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
            | Q(jurisdiction__icontains=q)
        )
    if status:
        qs = qs.filter(status=status)
    if scale:
        qs = qs.filter(scale=scale)
    return qs.order_by("-updated_at")


def validate_matter_scale(*, scale: str, jurisdiction: str) -> None:
    """Refuse une juridiction dont l'échelle ne correspond pas."""
    scale = scale or MatterScale.NATIONAL
    court = (jurisdiction or "").strip()
    if not court:
        return
    if scale == MatterScale.NATIONAL and court in international_jurisdiction_names():
        raise ValidationError(
            {
                "jurisdiction": _(
                    "Cette juridiction est internationale. Choisissez l'échelle internationale."
                )
            }
        )
    if scale == MatterScale.INTERNATIONAL and court in national_jurisdiction_names():
        raise ValidationError(
            {"jurisdiction": _("Cette juridiction est nationale. Choisissez l'échelle nationale.")}
        )


@transaction.atomic
def create_matter(
    *,
    user: User,
    title: str,
    cabinet: Cabinet | None = None,
    responsible_lawyer: User | None = None,
    description: str = "",
    practice_area: str = "",
    jurisdiction: str = "",
    scale: str = MatterScale.NATIONAL,
    status: str = MatterStatus.OPEN,
    opened_at: date | None = None,
    closed_at: date | None = None,
    notes: str = "",
    **_ignored: Any,
) -> Matter:
    """Crée un dossier ministériel : sans cabinet (rattaché à la procuration)."""
    if not is_platform_admin(user):
        raise PermissionDenied(_("Seul le Ministère de la Justice peut ouvrir un dossier."))
    if not title.strip():
        raise ValidationError({"title": _("L'intitulé est obligatoire.")})

    # Le cabinet n'est pas associé à la création : uniquement via la procuration.
    cabinet = None
    responsible_lawyer = None

    scale = scale or MatterScale.NATIONAL
    validate_matter_scale(scale=scale, jurisdiction=jurisdiction)
    matter = Matter(
        cabinet=None,
        created_by=user,
        responsible_lawyer=None,
        reference=allocate_matter_reference(cabinet=None),
        title=title.strip(),
        description=description,
        practice_area=practice_area,
        jurisdiction=jurisdiction,
        scale=scale,
        status=status,
        opened_at=opened_at or timezone.localdate(),
        closed_at=closed_at,
        notes=notes,
    )
    matter.save()
    refresh_matter_search_vector(matter)
    log_matter_action(
        matter=matter,
        user=user,
        action="created",
        message=_("Dossier créé (cabinet à désigner via procuration)."),
    )
    return matter


@transaction.atomic
def assign_matter_cabinet(
    *,
    matter: Matter,
    cabinet: Cabinet,
    actor: User | None = None,
) -> Matter:
    """Rattache un cabinet au dossier (lors de la délivrance de la procuration)."""
    from apps.tenants.models import Membership
    from apps.tenants.roles import Role

    if matter.cabinet_id and matter.cabinet_id != cabinet.pk:
        raise ValidationError(
            _("Ce dossier est déjà rattaché à un autre cabinet d'avocats.")
        )
    lawyer = (
        Membership.objects.filter(
            cabinet=cabinet,
            is_active=True,
            is_deleted=False,
            role__in=(Role.LAWYER, Role.CAIMAN),
        )
        .select_related("user")
        .order_by("role")
        .first()
    )
    matter.cabinet = cabinet
    if matter.responsible_lawyer_id is None and lawyer is not None:
        matter.responsible_lawyer = lawyer.user
    matter.save(update_fields=["cabinet", "responsible_lawyer", "updated_at"])
    from apps.matters.models import MatterAction, MatterParty

    MatterParty.unscoped.filter(matter=matter, cabinet__isnull=True).update(cabinet=cabinet)
    MatterAction.unscoped.filter(matter=matter, cabinet__isnull=True).update(cabinet=cabinet)
    if matter.responsible_lawyer_id and not MatterLawyer.objects.filter(matter=matter).exists():
        MatterLawyer.objects.create(
            matter=matter,
            lawyer=matter.responsible_lawyer,
            is_lead=True,
            assigned_by=actor,
        )
    log_matter_action(
        matter=matter,
        user=actor,
        action="cabinet_assigned",
        message=_("Cabinet rattaché via procuration : %(name)s") % {"name": cabinet.name},
    )
    return matter


@transaction.atomic
def assign_matter_lawyers(
    *,
    matter: Matter,
    user: User,
    lawyers: list[User],
    lead: User | None = None,
) -> Matter:
    """Affecte un ou plusieurs avocats du cabinet au dossier (cabinet uniquement)."""
    from apps.procurations.services import require_valid_procuration
    from apps.tenants.models import Membership
    from apps.tenants.roles import Role
    from apps.tenants.services import user_has_cabinet_perm
    from apps.tenants.roles import PERM_CHANGE

    if is_platform_admin(user):
        raise PermissionDenied(
            _("L'affectation des avocats est réservée au cabinet titulaire de la procuration.")
        )
    if matter.cabinet_id is None:
        raise ValidationError(_("Aucun cabinet n'est encore rattaché à ce dossier."))
    if matter.is_archived:
        raise ValidationError(_("Impossible d'affecter des avocats à un dossier archivé."))
    if not user_has_cabinet_perm(user=user, cabinet=matter.cabinet, perm=PERM_CHANGE):
        raise PermissionDenied(_("Vous n'avez pas le droit d'affecter des avocats à ce dossier."))
    require_valid_procuration(matter)

    if not lawyers:
        raise ValidationError(_("Sélectionnez au moins un avocat."))

    allowed_ids = set(
        Membership.objects.filter(
            cabinet=matter.cabinet,
            is_active=True,
            is_deleted=False,
            role__in=(Role.LAWYER, Role.CAIMAN),
            user_id__in=[lawyer.pk for lawyer in lawyers],
        ).values_list("user_id", flat=True)
    )
    if len(allowed_ids) != len({lawyer.pk for lawyer in lawyers}):
        raise ValidationError(
            _("Tous les avocats sélectionnés doivent appartenir au cabinet du dossier.")
        )

    unique_lawyers = list({lawyer.pk: lawyer for lawyer in lawyers}.values())
    if lead is None:
        lead = unique_lawyers[0]
    elif lead.pk not in {lawyer.pk for lawyer in unique_lawyers}:
        raise ValidationError(_("L'avocat responsable doit faire partie des avocats affectés."))

    MatterLawyer.objects.filter(matter=matter).delete()
    MatterLawyer.objects.bulk_create(
        [
            MatterLawyer(
                matter=matter,
                lawyer=lawyer,
                is_lead=(lawyer.pk == lead.pk),
                assigned_by=user,
            )
            for lawyer in unique_lawyers
        ]
    )
    matter.responsible_lawyer = lead
    matter.save(update_fields=["responsible_lawyer", "updated_at"])
    names = ", ".join(
        (lawyer.get_full_name() or lawyer.email) for lawyer in unique_lawyers
    )
    log_matter_action(
        matter=matter,
        user=user,
        action="lawyers_assigned",
        message=_("Avocats affectés : %(names)s") % {"names": names},
    )
    return matter


@transaction.atomic
def update_matter(*, matter: Matter, user: User, **fields: Any) -> Matter:
    """Met à jour un dossier — réservé au Ministère de la Justice."""
    if not is_platform_admin(user):
        raise PermissionDenied(_("Seul le Ministère de la Justice peut modifier un dossier."))
    fields.pop("target_cabinet", None)
    fields.pop("client", None)
    fields.pop("responsible_lawyer", None)
    old_status = matter.status
    incoming_status = fields.get("status", matter.status)
    if incoming_status == MatterStatus.IN_PROGRESS:
        from apps.procurations.services import require_valid_procuration

        require_valid_procuration(matter)
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
    """Archive un dossier clos — réservé au Ministère de la Justice."""
    if not is_platform_admin(user):
        raise PermissionDenied(_("Seul le Ministère de la Justice peut archiver un dossier."))
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
    """Suppression logique — réservée au Ministère de la Justice."""
    if not is_platform_admin(user):
        raise PermissionDenied(_("Seul le Ministère de la Justice peut supprimer un dossier."))
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
