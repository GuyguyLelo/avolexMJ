"""Services de gestion des utilisateurs (SuperAdmin)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Count, Q, QuerySet
from django.utils.translation import gettext_lazy as _

from apps.tenants.services import (
    detach_user_from_all_cabinets,
    require_super_admin,
)

if TYPE_CHECKING:
    from apps.accounts.models import User

logger = logging.getLogger(__name__)
UserModel = get_user_model()

ACCOUNT_CABINET = "cabinet"
ACCOUNT_ADMIN = "administrator"
ACCOUNT_SUPER = "superadmin"

ACCOUNT_TYPE_CHOICES = (
    (ACCOUNT_CABINET, _("Compte cabinet")),
    (ACCOUNT_ADMIN, _("Administrateur ministère")),
    (ACCOUNT_SUPER, _("SuperAdmin")),
)


def users_queryset(*, q: str = "", status: str = "", role: str = "") -> QuerySet[User]:
    """Liste annotée des comptes, filtrable."""
    qs = (
        UserModel.objects.all()
        .annotate(
            memberships_count=Count(
                "memberships",
                filter=Q(memberships__is_active=True),
                distinct=True,
            )
        )
        .order_by("last_name", "first_name", "email")
    )
    term = (q or "").strip()
    if term:
        qs = qs.filter(
            Q(email__icontains=term)
            | Q(first_name__icontains=term)
            | Q(last_name__icontains=term)
            | Q(phone__icontains=term)
        )
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)
    if role == "super":
        qs = qs.filter(is_super_admin=True)
    elif role == "platform":
        qs = qs.filter(is_platform_admin=True, is_super_admin=False)
    elif role == "cabinet":
        qs = qs.filter(is_platform_admin=False, is_super_admin=False)
    return qs


def account_type_of(user: User) -> str:
    """Type de compte pour affichage / formulaire."""
    if getattr(user, "is_super_admin", False):
        return ACCOUNT_SUPER
    if getattr(user, "is_platform_admin", False):
        return ACCOUNT_ADMIN
    return ACCOUNT_CABINET


def _flags_from_account_type(account_type: str) -> tuple[bool, bool]:
    if account_type == ACCOUNT_SUPER:
        return True, True
    if account_type == ACCOUNT_ADMIN:
        return True, False
    return False, False


def _normalize_email(email: str) -> str:
    return UserModel.objects.normalize_identifier(email)


def create_user_as_platform_admin(
    *,
    actor: User,
    email: str,
    password: str,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    account_type: str = ACCOUNT_CABINET,
    is_active: bool = True,
    cabinet: object | None = None,
    cabinet_role: str | None = None,
) -> User:
    """Crée un compte (SuperAdmin uniquement)."""
    from django.db import transaction

    from apps.tenants.models import Membership
    from apps.tenants.roles import Role
    from apps.tenants.services import ensure_user_can_join_cabinet

    require_super_admin(actor)
    if account_type not in {ACCOUNT_CABINET, ACCOUNT_ADMIN, ACCOUNT_SUPER}:
        raise ValidationError({"account_type": _("Type de compte invalide.")})
    normalized = _normalize_email(email)
    if not normalized:
        raise ValidationError({"email": _("L'identifiant est obligatoire.")})
    if UserModel.objects.filter(email__iexact=normalized).exists():
        raise ValidationError({"email": _("Un compte existe déjà avec cet identifiant.")})
    validate_password(password)
    is_platform, is_super = _flags_from_account_type(account_type)

    if account_type == ACCOUNT_CABINET:
        if cabinet is None:
            raise ValidationError(
                {"cabinet": _("Le cabinet d'avocats est obligatoire pour un compte cabinet.")}
            )
        role = cabinet_role or Role.LAWYER
        if role not in {choice[0] for choice in Role.choices}:
            raise ValidationError({"cabinet_role": _("Rôle cabinet invalide.")})

    with transaction.atomic():
        user = UserModel.objects.create_user(
            email=normalized,
            password=password,
            first_name=(first_name or "").strip(),
            last_name=(last_name or "").strip(),
            phone=(phone or "").strip(),
            is_platform_admin=is_platform,
            is_super_admin=is_super,
            is_active=bool(is_active),
        )
        # SuperAdmin / Admin : jamais de rattachement cabinet.
        if is_platform or is_super:
            detach_user_from_all_cabinets(user)
        elif account_type == ACCOUNT_CABINET:
            ensure_user_can_join_cabinet(user)
            Membership.objects.create(
                cabinet=cabinet,
                user=user,
                role=cabinet_role or Role.LAWYER,
                is_active=True,
                created_by=actor,
            )
    logger.info(
        "Utilisateur créé id=%s email=%s type=%s actor=%s",
        user.pk,
        user.email,
        account_type,
        actor.pk,
    )
    return user


def update_user_as_platform_admin(
    *,
    actor: User,
    user: User,
    email: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
    password: str | None = None,
    account_type: str | None = None,
    is_active: bool | None = None,
) -> User:
    """Met à jour un compte (SuperAdmin uniquement)."""
    require_super_admin(actor)
    update_fields: list[str] = []

    if email is not None:
        normalized = _normalize_email(email)
        if not normalized:
            raise ValidationError({"email": _("L'identifiant est obligatoire.")})
        if (
            UserModel.objects.filter(email__iexact=normalized)
            .exclude(pk=user.pk)
            .exists()
        ):
            raise ValidationError({"email": _("Un compte existe déjà avec cet identifiant.")})
        user.email = normalized
        update_fields.append("email")

    if first_name is not None:
        user.first_name = first_name.strip()
        update_fields.append("first_name")
    if last_name is not None:
        user.last_name = last_name.strip()
        update_fields.append("last_name")
    if phone is not None:
        user.phone = phone.strip()
        update_fields.append("phone")

    if account_type is not None:
        if account_type not in {ACCOUNT_CABINET, ACCOUNT_ADMIN, ACCOUNT_SUPER}:
            raise ValidationError({"account_type": _("Type de compte invalide.")})
        is_platform, is_super = _flags_from_account_type(account_type)
        if user.is_super_admin and not is_super:
            _ensure_not_last_super_admin(user)
        elif user.is_platform_admin and not is_platform and not is_super:
            _ensure_not_last_ministry_admin(user)
        # Promotion SuperAdmin / Admin : détacher de tout cabinet d'avocats.
        if is_platform or is_super:
            detach_user_from_all_cabinets(user)
        user.is_platform_admin = is_platform
        user.is_super_admin = is_super
        update_fields.extend(["is_platform_admin", "is_super_admin"])

    if is_active is not None:
        new_active = bool(is_active)
        if user.is_active and not new_active:
            if user.pk == actor.pk:
                raise ValidationError(_("Vous ne pouvez pas désactiver votre propre compte."))
            if user.is_super_admin:
                _ensure_not_last_super_admin(user)
            elif user.is_platform_admin:
                _ensure_not_last_ministry_admin(user)
        user.is_active = new_active
        update_fields.append("is_active")

    if password:
        validate_password(password, user=user)
        user.set_password(password)
        update_fields.append("password")

    if update_fields:
        user.save(update_fields=list(dict.fromkeys(update_fields)))
        logger.info(
            "Utilisateur mis à jour id=%s fields=%s actor=%s",
            user.pk,
            ",".join(update_fields),
            actor.pk,
        )
    return user


def deactivate_user_as_platform_admin(*, actor: User, user: User) -> User:
    """Désactive un compte (soft)."""
    return update_user_as_platform_admin(actor=actor, user=user, is_active=False)


def update_own_profile(
    *,
    user: User,
    first_name: str = "",
    last_name: str = "",
    phone: str = "",
    password: str | None = None,
) -> User:
    """Met à jour le profil du compte connecté (identité + mot de passe optionnel)."""
    user.first_name = (first_name or "").strip()
    user.last_name = (last_name or "").strip()
    user.phone = (phone or "").strip()
    update_fields = ["first_name", "last_name", "phone"]
    if password:
        validate_password(password, user=user)
        user.set_password(password)
        update_fields.append("password")
    user.save(update_fields=update_fields)
    logger.info("Profil mis à jour id=%s fields=%s", user.pk, ",".join(update_fields))
    return user


def _ensure_not_last_super_admin(user: User) -> None:
    others = UserModel.objects.filter(is_super_admin=True, is_active=True).exclude(pk=user.pk)
    if not others.exists():
        raise ValidationError(
            _("Impossible : il doit rester au moins un SuperAdmin actif.")
        )


def _ensure_not_last_ministry_admin(user: User) -> None:
    others = UserModel.objects.filter(
        is_platform_admin=True,
        is_active=True,
    ).exclude(pk=user.pk)
    if not others.exists():
        raise ValidationError(
            _("Impossible : il doit rester au moins un administrateur ministère actif.")
        )


def user_memberships(user: User) -> QuerySet:
    """Adhésions actives d'un utilisateur."""
    from apps.tenants.models import Membership

    return (
        Membership.objects.filter(user=user, is_active=True)
        .select_related("cabinet")
        .order_by("cabinet__name")
    )
