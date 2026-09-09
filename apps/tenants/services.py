"""Services métier multi-tenant (pas de logique dans les vues)."""

from __future__ import annotations

import logging
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.tenants.models import Cabinet, Invitation, Membership
from apps.tenants.roles import (
    PERM_INVITE,
    PERM_MANAGE_CABINET,
    PERM_MANAGE_MEMBERS,
    PERM_VIEW,
    Role,
    role_has_perm,
)

if TYPE_CHECKING:
    from django.http import HttpRequest

    from apps.accounts.models import User

logger = logging.getLogger(__name__)
UserModel = get_user_model()

SESSION_CABINET_KEY = "cabinet_id"

CABINET_EDITABLE_FIELDS = frozenset(
    {
        "name",
        "contract_number",
        "legal_name",
        "siret",
        "vat_number",
        "bar_association",
        "address_line1",
        "address_line2",
        "postal_code",
        "city",
        "country",
        "default_currency",
        "retention_days",
        "is_active",
    }
)


def is_super_admin(user: User | None) -> bool:
    """Indique si l'utilisateur est SuperAdmin."""
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_super_admin", False)
    )


def is_platform_admin(user: User | None) -> bool:
    """Administrateur ministère ou SuperAdmin (accès opérationnel plateforme)."""
    return bool(
        user
        and getattr(user, "is_authenticated", False)
        and (
            getattr(user, "is_super_admin", False)
            or getattr(user, "is_platform_admin", False)
        )
    )


def can_manage_users(user: User | None) -> bool:
    """Seul le SuperAdmin gère les comptes (admins et cabinets)."""
    return is_super_admin(user)


def require_platform_admin(user: User) -> None:
    """Lève PermissionDenied si l'utilisateur n'est pas admin ministère / SuperAdmin."""
    if not is_platform_admin(user):
        raise PermissionDenied(_("Réservé à l'administrateur du Ministère de la Justice."))


def require_super_admin(user: User) -> None:
    """Lève PermissionDenied si l'utilisateur n'est pas SuperAdmin."""
    if not is_super_admin(user):
        raise PermissionDenied(_("Réservé au SuperAdmin."))


def ensure_user_can_join_cabinet(user: User) -> None:
    """SuperAdmin et Administrateur ministère ne peuvent pas être rattachés à un cabinet."""
    if is_platform_admin(user):
        raise ValidationError(
            _(
                "Un SuperAdmin ou un Administrateur n'est pas lié à un cabinet d'avocats."
            )
        )


def detach_user_from_all_cabinets(user: User) -> int:
    """
    Retire toutes les adhésions actives (ex. promotion SuperAdmin / Admin).

    Raises:
        ValidationError: si l'utilisateur est le dernier Caïman d'un cabinet.
    """
    memberships = list(
        Membership.objects.filter(user=user, is_active=True, is_deleted=False).select_related(
            "cabinet"
        )
    )
    for membership in memberships:
        if (
            membership.role == Role.CAIMAN
            and _active_owner_count(membership.cabinet, exclude_pk=membership.pk) == 0
        ):
            raise ValidationError(
                _(
                    "Impossible : %(user)s est le dernier Caïman de « %(cabinet)s ». "
                    "Désignez un autre Caïman avant de retirer le rattachement."
                )
                % {"user": user.email, "cabinet": membership.cabinet.name}
            )
    for membership in memberships:
        membership.is_active = False
        membership.soft_delete(save=False)
        membership.save(
            update_fields=["is_active", "is_deleted", "deleted_at", "updated_at"]
        )
    return len(memberships)


def get_membership(*, user: User, cabinet: Cabinet) -> Membership | None:
    """Retourne l'adhésion active d'un utilisateur pour un cabinet."""
    return (
        Membership.objects.select_related("cabinet", "user")
        .filter(user=user, cabinet=cabinet, is_active=True)
        .first()
    )


def user_has_cabinet_perm(*, user: User, cabinet: Cabinet, perm: str) -> bool:
    """Vérifie qu'un utilisateur a une permission logique sur un cabinet."""
    if is_platform_admin(user):
        # Supervision : lecture seule sur tous les cabinets.
        return perm == PERM_VIEW
    membership = get_membership(user=user, cabinet=cabinet)
    if membership is None:
        return False
    return role_has_perm(membership.role, perm)


def require_cabinet_perm(*, user: User, cabinet: Cabinet, perm: str) -> Membership | None:
    """Comme user_has_cabinet_perm mais lève PermissionDenied.

    Pour un admin plateforme en lecture seule, retourne None (pas d'adhésion).
    """
    if is_platform_admin(user):
        if perm != PERM_VIEW:
            raise PermissionDenied(_("Supervision plateforme : lecture seule."))
        return get_membership(user=user, cabinet=cabinet)
    membership = get_membership(user=user, cabinet=cabinet)
    if membership is None or not role_has_perm(membership.role, perm):
        raise PermissionDenied(_("Permission refusée pour ce cabinet."))
    return membership


def list_user_cabinets(user: User) -> list[Cabinet]:
    """Liste les cabinets visibles : adhésions, ou tous si admin plateforme."""
    if is_platform_admin(user):
        return list(Cabinet.objects.filter(is_active=True).order_by("name"))
    return list(
        Cabinet.objects.filter(
            memberships__user=user,
            memberships__is_active=True,
            memberships__is_deleted=False,
            is_active=True,
        )
        .distinct()
        .order_by("name")
    )


@transaction.atomic
def create_cabinet_with_owner(
    *,
    owner: User,
    name: str,
    **extra_fields: object,
) -> tuple[Cabinet, Membership]:
    """
    Crée un cabinet et y rattache l'utilisateur comme Owner.

    Returns:
        Couple (cabinet, membership).
    """
    ensure_user_can_join_cabinet(owner)
    cabinet = Cabinet(name=name, created_by=owner, **extra_fields)  # type: ignore[arg-type]
    cabinet.save()
    membership = Membership.objects.create(
        cabinet=cabinet,
        user=owner,
        role=Role.CAIMAN,
        created_by=owner,
    )
    logger.info("Cabinet créé id=%s owner=%s", cabinet.pk, owner.pk)
    return cabinet, membership


def cabinets_queryset(*, q: str = "") -> QuerySet[Cabinet]:
    """Liste des cabinets (supervision) avec nombre de membres, filtre optionnel."""
    qs = Cabinet.objects.annotate(
        members_count=Count(
            "memberships",
            filter=Q(memberships__is_active=True, memberships__is_deleted=False),
        )
    ).order_by("name")
    q = (q or "").strip()
    if not q:
        return qs
    return qs.filter(
        Q(name__icontains=q)
        | Q(slug__icontains=q)
        | Q(legal_name__icontains=q)
        | Q(city__icontains=q)
        | Q(bar_association__icontains=q)
        | Q(siret__icontains=q)
        | Q(contract_number__icontains=q)
    )


CONTRACT_ALLOWED_EXTENSIONS = frozenset({".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png", ".webp"})
CONTRACT_ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/jpeg",
        "image/png",
        "image/webp",
    }
)


def validate_cabinet_contract_file(uploaded: UploadedFile) -> None:
    """Autorise PDF, DOC, DOCX et images, dans la limite GED."""
    from apps.documents.services import get_max_upload_bytes

    name = getattr(uploaded, "name", "") or ""
    ext = PurePosixPath(name).suffix.lower()
    if ext not in CONTRACT_ALLOWED_EXTENSIONS:
        raise ValidationError(_("Le contrat doit être un PDF, DOC, DOCX ou une image."))
    mime = (getattr(uploaded, "content_type", None) or "").split(";")[0].strip().lower()
    if mime and mime not in CONTRACT_ALLOWED_MIME_TYPES:
        raise ValidationError(_("Le contrat doit être un PDF, DOC, DOCX ou une image."))
    size = getattr(uploaded, "size", None)
    max_bytes = get_max_upload_bytes()
    if size is not None and size <= 0:
        raise ValidationError(_("Fichier vide."))
    if size is not None and size > max_bytes:
        raise ValidationError(
            _("Fichier trop volumineux (max %(max)s Mo).")
            % {"max": max_bytes // (1024 * 1024)}
        )


def attach_cabinet_contract(
    *,
    cabinet: Cabinet,
    uploaded: UploadedFile | None | bool,
) -> None:
    """Joint, remplace ou retire le contrat d'un cabinet."""
    if uploaded is False:
        if cabinet.contract_file:
            cabinet.contract_file.delete(save=False)
        cabinet.contract_file = ""
        cabinet.contract_file_name = ""
        cabinet.save(update_fields=["contract_file", "contract_file_name", "updated_at"])
        return
    if not uploaded:
        return
    validate_cabinet_contract_file(uploaded)
    if cabinet.contract_file:
        cabinet.contract_file.delete(save=False)
    name = getattr(uploaded, "name", "contrat.pdf") or "contrat.pdf"
    cabinet.contract_file = uploaded
    cabinet.contract_file_name = str(name)[:255]
    cabinet.save(update_fields=["contract_file", "contract_file_name", "updated_at"])


@transaction.atomic
def create_cabinet_as_platform_admin(
    *,
    actor: User,
    name: str,
    owner_email: str,
    owner_first_name: str = "",
    owner_last_name: str = "",
    **extra_fields: object,
) -> tuple[Cabinet, Membership, User]:
    """
    Crée un cabinet depuis la supervision, avec un propriétaire.

    Si l'e-mail existe déjà, l'utilisateur est rattaché comme Owner.
    Sinon un compte est créé sans mot de passe (défini ensuite dans la gestion des utilisateurs).
    """
    require_platform_admin(actor)
    email = owner_email.strip().lower()
    if not email:
        raise ValidationError({"owner_email": _("L'e-mail du Caïman est obligatoire.")})
    if not (name or "").strip():
        raise ValidationError({"name": _("Le nom du cabinet est obligatoire.")})

    extra_fields = {k: v for k, v in extra_fields.items() if k in CABINET_EDITABLE_FIELDS}
    extra_fields.pop("name", None)

    user = UserModel.objects.filter(email__iexact=email).first()
    if user is None:
        user = UserModel.objects.create_user(
            email=email,
            password=None,
            first_name=owner_first_name.strip(),
            last_name=owner_last_name.strip(),
        )
    else:
        ensure_user_can_join_cabinet(user)  # type: ignore[arg-type]
        changed: list[str] = []
        if owner_first_name.strip() and not user.first_name:
            user.first_name = owner_first_name.strip()
            changed.append("first_name")
        if owner_last_name.strip() and not user.last_name:
            user.last_name = owner_last_name.strip()
            changed.append("last_name")
        if changed:
            user.save(update_fields=changed)

    cabinet, membership = create_cabinet_with_owner(
        owner=user,
        name=name.strip(),
        **extra_fields,  # type: ignore[arg-type]
    )
    logger.info(
        "Cabinet plateforme créé id=%s owner=%s actor=%s",
        cabinet.pk,
        user.pk,
        actor.pk,
    )
    return cabinet, membership, user


@transaction.atomic
def update_cabinet_as_platform_admin(
    *,
    actor: User,
    cabinet: Cabinet,
    **fields: object,
) -> Cabinet:
    """Met à jour les informations d'un cabinet (supervision)."""
    require_platform_admin(actor)
    name = fields.get("name", cabinet.name)
    if not str(name or "").strip():
        raise ValidationError({"name": _("Le nom du cabinet est obligatoire.")})
    for key, value in fields.items():
        if key in CABINET_EDITABLE_FIELDS:
            setattr(cabinet, key, value)
    cabinet.save()
    logger.info("Cabinet plateforme mis à jour id=%s actor=%s", cabinet.pk, actor.pk)
    return cabinet


@transaction.atomic
def delete_cabinet_as_platform_admin(*, actor: User, cabinet: Cabinet) -> None:
    """Désactive et supprime logiquement un cabinet (supervision)."""
    require_platform_admin(actor)
    cabinet.is_active = False
    cabinet.soft_delete(save=False)
    cabinet.save(update_fields=["is_active", "is_deleted", "deleted_at", "updated_at"])
    logger.info("Cabinet plateforme supprimé id=%s actor=%s", cabinet.pk, actor.pk)


@transaction.atomic
def register_user_with_cabinet(
    *,
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    cabinet_name: str,
) -> tuple[User, Cabinet, Membership]:
    """Inscription : crée l'utilisateur, le cabinet et l'adhésion Owner."""
    if UserModel.objects.filter(email__iexact=email).exists():
        raise ValidationError({"email": _("Un compte existe déjà avec cet e-mail.")})
    user = UserModel.objects.create_user(
        email=email,
        password=password,
        first_name=first_name,
        last_name=last_name,
    )
    cabinet, membership = create_cabinet_with_owner(owner=user, name=cabinet_name)
    return user, cabinet, membership


def set_session_cabinet(request: HttpRequest, cabinet: Cabinet) -> None:
    """Enregistre le cabinet courant en session."""
    request.session[SESSION_CABINET_KEY] = str(cabinet.pk)


def clear_session_cabinet(request: HttpRequest) -> None:
    """Retire le cabinet de la session."""
    request.session.pop(SESSION_CABINET_KEY, None)


def switch_cabinet(*, request: HttpRequest, user: User, cabinet_id: str) -> Cabinet:
    """
    Change le cabinet courant si l'utilisateur y a une adhésion active.

    Les comptes ministère ne sont pas rattachés à un cabinet : le basculement
    est refusé (ils gèrent les cabinets via la supervision / liste).

    Raises:
        PermissionDenied: si aucune adhésion active ou compte ministère.
        Cabinet.DoesNotExist: si le cabinet est introuvable.
    """
    cabinet = Cabinet.objects.get(pk=cabinet_id, is_active=True)
    if is_platform_admin(user):
        raise PermissionDenied(
            _("Un compte ministère n'est pas lié à un cabinet d'avocats.")
        )
    membership = get_membership(user=user, cabinet=cabinet)
    if membership is None:
        raise PermissionDenied(_("Vous n'appartenez pas à ce cabinet."))
    set_session_cabinet(request, cabinet)
    return cabinet


@transaction.atomic
def invite_member(
    *,
    cabinet: Cabinet,
    email: str,
    role: str,
    invited_by: User,
) -> Invitation:
    """Crée (ou renouvelle) une invitation pour un e-mail."""
    require_cabinet_perm(user=invited_by, cabinet=cabinet, perm=PERM_INVITE)

    if not role_has_perm(role, PERM_VIEW):
        raise ValidationError({"role": _("Rôle invalide.")})

    email_norm = email.strip().lower()
    existing_user = UserModel.objects.filter(email__iexact=email_norm).first()
    if existing_user is not None:
        ensure_user_can_join_cabinet(existing_user)  # type: ignore[arg-type]
        if get_membership(user=existing_user, cabinet=cabinet):
            raise ValidationError(_("Cet utilisateur est déjà membre du cabinet."))

    Invitation.objects.filter(
        cabinet=cabinet,
        email__iexact=email_norm,
        accepted_at__isnull=True,
        is_deleted=False,
    ).update(is_deleted=True, deleted_at=timezone.now())

    invitation = Invitation.objects.create(
        cabinet=cabinet,
        email=email_norm,
        role=role,
        invited_by=invited_by,
        created_by=invited_by,
    )
    logger.info(
        "Invitation créée cabinet=%s email=%s role=%s",
        cabinet.pk,
        email_norm,
        role,
    )
    return invitation


@transaction.atomic
def accept_invitation(
    *,
    token: str,
    user: User | None = None,
    password: str | None = None,
    first_name: str = "",
    last_name: str = "",
) -> tuple[User, Membership, Invitation]:
    """
    Accepte une invitation.

    Si ``user`` est None, crée un compte avec ``password``.
    """
    try:
        invitation = Invitation.objects.select_related("cabinet").get(
            token=token,
            is_deleted=False,
        )
    except Invitation.DoesNotExist as exc:
        raise ValidationError(_("Invitation introuvable.")) from exc

    if invitation.is_accepted:
        raise ValidationError(_("Cette invitation a déjà été acceptée."))
    if invitation.is_expired:
        raise ValidationError(_("Cette invitation a expiré."))

    if user is None:
        if not password:
            raise ValidationError({"password": _("Mot de passe obligatoire.")})
        existing = UserModel.objects.filter(email__iexact=invitation.email).first()
        if existing:
            raise ValidationError(
                _("Un compte existe déjà pour cet e-mail. Connectez-vous puis acceptez.")
            )
        user = UserModel.objects.create_user(
            email=invitation.email,
            password=password,
            first_name=first_name,
            last_name=last_name,
        )
    elif user.email.lower() != invitation.email.lower():
        raise ValidationError(_("Cette invitation est destinée à une autre adresse e-mail."))

    membership, _created = Membership.objects.get_or_create(
        cabinet=invitation.cabinet,
        user=user,
        defaults={
            "role": invitation.role,
            "is_active": True,
            "created_by": user,
        },
    )
    if not _created:
        membership.role = invitation.role
        membership.is_active = True
        membership.is_deleted = False
        membership.deleted_at = None
        membership.save()

    invitation.accepted_at = timezone.now()
    invitation.save(update_fields=["accepted_at", "updated_at"])
    return user, membership, invitation


def resolve_cabinet_for_request(request: HttpRequest) -> Cabinet | None:
    """
    Résout le cabinet courant depuis la session.

    Les comptes ministère (Admin / SuperAdmin) ne sont jamais rattachés à un cabinet :
    pas de cabinet courant automatique.
    Pour un compte cabinet, si aucun cabinet en session, prend le premier.
    """
    user = request.user
    if not user.is_authenticated:
        return None

    if is_platform_admin(user):  # type: ignore[arg-type]
        # Compte ministère : pas de rattachement à un cabinet d'avocats.
        if SESSION_CABINET_KEY in request.session:
            del request.session[SESSION_CABINET_KEY]
        return None

    cabinets = list_user_cabinets(user)  # type: ignore[arg-type]
    if not cabinets:
        return None

    raw_id = request.session.get(SESSION_CABINET_KEY)
    if raw_id:
        for cabinet in cabinets:
            if str(cabinet.pk) == str(raw_id):
                return cabinet

    cabinet = cabinets[0]
    set_session_cabinet(request, cabinet)
    return cabinet


def can_manage_members(*, user: User, cabinet: Cabinet) -> bool:
    """True si le ministère ou le Caïman peut gérer l'équipe."""
    if is_platform_admin(user):
        return True
    return user_has_cabinet_perm(user=user, cabinet=cabinet, perm=PERM_MANAGE_MEMBERS)


def can_manage_cabinet(*, user: User, cabinet: Cabinet) -> bool:
    """True si le ministère ou le Caïman peut gérer le cabinet."""
    if is_platform_admin(user):
        return True
    return user_has_cabinet_perm(user=user, cabinet=cabinet, perm=PERM_MANAGE_CABINET)


def require_manage_members(*, user: User, cabinet: Cabinet) -> None:
    """Lève PermissionDenied si l'acteur ne peut pas gérer les membres."""
    if not can_manage_members(user=user, cabinet=cabinet):
        raise PermissionDenied(_("Vous ne pouvez pas gérer les membres de ce cabinet."))


def require_manage_cabinet_settings(*, user: User, cabinet: Cabinet) -> None:
    """Lève PermissionDenied si l'acteur ne peut pas gérer les spécialités."""
    if not can_manage_cabinet(user=user, cabinet=cabinet):
        raise PermissionDenied(_("Vous ne pouvez pas gérer les spécialités de ce cabinet."))


def memberships_queryset(
    *, cabinet: Cabinet, include_inactive: bool = True
) -> QuerySet[Membership]:
    """Membres d'un cabinet, actifs d'abord."""
    qs = Membership.objects.filter(cabinet=cabinet).select_related("user")
    if not include_inactive:
        qs = qs.filter(is_active=True)
    return qs.order_by("-is_active", "role", "user__last_name", "user__email")


def _active_owner_count(cabinet: Cabinet, *, exclude_pk: object | None = None) -> int:
    qs = Membership.objects.filter(cabinet=cabinet, role=Role.CAIMAN, is_active=True)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.count()


def _validate_assignable_role(*, actor: User, role: str) -> None:
    if role not in {choice[0] for choice in Role.choices}:
        raise ValidationError({"role": _("Rôle invalide.")})


@transaction.atomic
def add_cabinet_member(
    *,
    actor: User,
    cabinet: Cabinet,
    email: str,
    role: str,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    password: str | None = None,
) -> Membership:
    """Ajoute un membre au cabinet (crée le compte si besoin)."""
    require_manage_members(user=actor, cabinet=cabinet)
    _validate_assignable_role(actor=actor, role=role)
    email_norm = email.strip().lower()
    if not email_norm:
        raise ValidationError({"email": _("L'e-mail est obligatoire.")})

    user = UserModel.objects.filter(email__iexact=email_norm).first()
    if user is None:
        user = UserModel.objects.create_user(
            email=email_norm,
            password=password or None,
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            phone=phone.strip(),
        )
    else:
        ensure_user_can_join_cabinet(user)  # type: ignore[arg-type]
        changed: list[str] = []
        if first_name.strip() and not user.first_name:
            user.first_name = first_name.strip()
            changed.append("first_name")
        if last_name.strip() and not user.last_name:
            user.last_name = last_name.strip()
            changed.append("last_name")
        if phone.strip() and not user.phone:
            user.phone = phone.strip()
            changed.append("phone")
        if password:
            user.set_password(password)
            changed.append("password")
        if changed:
            user.save(update_fields=changed)

    membership = Membership.all_objects.filter(cabinet=cabinet, user=user).first()
    if membership is not None:
        if not membership.is_deleted and membership.is_active:
            raise ValidationError(_("Cet utilisateur est déjà membre du cabinet."))
        membership.role = role
        membership.is_active = True
        membership.is_deleted = False
        membership.deleted_at = None
        membership.save(
            update_fields=["role", "is_active", "is_deleted", "deleted_at", "updated_at"]
        )
        logger.info("Membre rétabli cabinet=%s user=%s", cabinet.pk, user.pk)
        return membership

    membership = Membership.objects.create(
        cabinet=cabinet,
        user=user,
        role=role,
        is_active=True,
        created_by=actor,
    )
    logger.info("Membre ajouté cabinet=%s user=%s role=%s", cabinet.pk, user.pk, role)
    return membership


@transaction.atomic
def update_cabinet_member(
    *,
    actor: User,
    membership: Membership,
    role: str | None = None,
    is_active: bool | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
) -> Membership:
    """Met à jour le rôle, le statut ou l'identité d'un membre."""
    require_manage_members(user=actor, cabinet=membership.cabinet)
    if role is not None and role != membership.role:
        _validate_assignable_role(actor=actor, role=role)
        if (
            membership.role == Role.CAIMAN
            and role != Role.CAIMAN
            and _active_owner_count(membership.cabinet, exclude_pk=membership.pk) == 0
        ):
            raise ValidationError(_("Impossible de retirer le dernier Caïman."))
        membership.role = role
    if is_active is not None and is_active != membership.is_active:
        if (
            not is_active
            and membership.role == Role.CAIMAN
            and membership.is_active
            and _active_owner_count(membership.cabinet, exclude_pk=membership.pk) == 0
        ):
            raise ValidationError(_("Impossible de désactiver le dernier Caïman."))
        membership.is_active = is_active
    membership.save(update_fields=["role", "is_active", "updated_at"])

    user = membership.user
    user_changed: list[str] = []
    if first_name is not None:
        user.first_name = first_name.strip()
        user_changed.append("first_name")
    if last_name is not None:
        user.last_name = last_name.strip()
        user_changed.append("last_name")
    if phone is not None:
        user.phone = phone.strip()
        user_changed.append("phone")
    if user_changed:
        user.save(update_fields=user_changed)
    return membership


@transaction.atomic
def remove_cabinet_member(*, actor: User, membership: Membership) -> None:
    """Retire un membre (désactivation + suppression logique)."""
    require_manage_members(user=actor, cabinet=membership.cabinet)
    if (
        membership.role == Role.CAIMAN
        and membership.is_active
        and _active_owner_count(membership.cabinet, exclude_pk=membership.pk) == 0
    ):
        raise ValidationError(_("Impossible de retirer le dernier Caïman."))
    membership.is_active = False
    membership.soft_delete(save=False)
    membership.save(update_fields=["is_active", "is_deleted", "deleted_at", "updated_at"])
    logger.info("Membre retiré cabinet=%s user=%s", membership.cabinet_id, membership.user_id)


def legal_practice_areas_queryset(*, q: str = "", active_only: bool = False) -> QuerySet[Any]:
    """Liste du référentiel de matières juridiques."""
    from apps.tenants.models import LegalPracticeArea

    qs = LegalPracticeArea.objects.all().order_by("name")
    if active_only:
        qs = qs.filter(is_active=True)
    q = (q or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
    return qs


@transaction.atomic
def create_legal_practice_area(
    *,
    actor: User,
    name: str,
    description: str = "",
    is_active: bool = True,
) -> Any:
    """Crée une matière du référentiel (ministère)."""
    from apps.tenants.models import LegalPracticeArea

    require_platform_admin(actor)
    label = (name or "").strip()
    if not label:
        raise ValidationError({"name": _("L'intitulé est obligatoire.")})
    if LegalPracticeArea.objects.filter(name__iexact=label).exists():
        raise ValidationError({"name": _("Cette matière existe déjà.")})
    area = LegalPracticeArea(
        name=label,
        description=(description or "").strip(),
        is_active=is_active,
        created_by=actor,
    )
    area.save()
    return area


@transaction.atomic
def update_legal_practice_area(
    *,
    actor: User,
    area: Any,
    name: str,
    description: str = "",
    is_active: bool = True,
) -> Any:
    """Met à jour une matière du référentiel."""
    from apps.tenants.models import LegalPracticeArea

    require_platform_admin(actor)
    label = (name or "").strip()
    if not label:
        raise ValidationError({"name": _("L'intitulé est obligatoire.")})
    if LegalPracticeArea.objects.filter(name__iexact=label).exclude(pk=area.pk).exists():
        raise ValidationError({"name": _("Cette matière existe déjà.")})
    area.name = label
    area.description = (description or "").strip()
    area.is_active = is_active
    area.save()
    return area


@transaction.atomic
def delete_legal_practice_area(*, actor: User, area: Any) -> None:
    """Supprime logiquement une matière du référentiel."""
    require_platform_admin(actor)
    area.is_active = False
    area.soft_delete(save=False)
    area.save(update_fields=["is_active", "is_deleted", "deleted_at", "updated_at"])


def cabinet_practice_areas_queryset(*, cabinet: Cabinet) -> QuerySet[Any]:
    """Spécialités actives d'un cabinet."""
    from apps.tenants.models import CabinetPracticeArea

    return (
        CabinetPracticeArea.objects.filter(cabinet=cabinet)
        .select_related("practice_area")
        .order_by("practice_area__name")
    )


@transaction.atomic
def add_cabinet_practice_area(
    *,
    actor: User,
    cabinet: Cabinet,
    practice_area: Any,
) -> Any:
    """Associe une matière au cabinet."""
    from apps.tenants.models import CabinetPracticeArea

    require_manage_cabinet_settings(user=actor, cabinet=cabinet)
    if not getattr(practice_area, "is_active", True):
        raise ValidationError({"practice_area": _("Cette matière n'est plus proposée.")})
    link = CabinetPracticeArea.all_objects.filter(
        cabinet=cabinet, practice_area=practice_area
    ).first()
    if link is not None:
        if not link.is_deleted:
            raise ValidationError(_("Cette spécialité est déjà enregistrée pour le cabinet."))
        link.is_deleted = False
        link.deleted_at = None
        link.save(update_fields=["is_deleted", "deleted_at", "updated_at"])
        return link
    return CabinetPracticeArea.objects.create(
        cabinet=cabinet,
        practice_area=practice_area,
        created_by=actor,
    )


@transaction.atomic
def remove_cabinet_practice_area(*, actor: User, link: Any) -> None:
    """Retire une spécialité du cabinet."""
    require_manage_cabinet_settings(user=actor, cabinet=link.cabinet)
    link.soft_delete()


def suggest_cabinets_for_practice_area(
    *,
    practice_area_name: str = "",
    practice_area_id: str = "",
) -> QuerySet[Cabinet]:
    """Cabinets actifs spécialisés dans une matière (pour l'ouverture d'un dossier)."""
    from apps.tenants.models import CabinetPracticeArea, LegalPracticeArea

    area = None
    if practice_area_id:
        area = LegalPracticeArea.objects.filter(pk=practice_area_id, is_active=True).first()
    if area is None and (practice_area_name or "").strip():
        area = LegalPracticeArea.objects.filter(
            name__iexact=practice_area_name.strip(),
            is_active=True,
        ).first()
    if area is None:
        return Cabinet.objects.none()
    cabinet_ids = CabinetPracticeArea.objects.filter(practice_area=area).values("cabinet_id")
    return Cabinet.objects.filter(pk__in=cabinet_ids, is_active=True).order_by("name")
