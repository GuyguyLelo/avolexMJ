"""Tests des services tenants."""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.tenants.models import Invitation, Membership
from apps.tenants.roles import Role, role_has_perm
from apps.tenants.services import (
    accept_invitation,
    create_cabinet_with_owner,
    invite_member,
    register_user_with_cabinet,
    user_has_cabinet_perm,
)
from tests.factories import CabinetFactory, InvitationFactory, MembershipFactory, UserFactory


@pytest.mark.django_db
def test_register_user_with_cabinet() -> None:
    """L'inscription crée user + cabinet + membership owner."""
    user, cabinet, membership = register_user_with_cabinet(
        email="owner@example.com",
        password="Str0ng-Passw0rd!",
        first_name="Ada",
        last_name="Lovelace",
        cabinet_name="Cabinet Ada",
    )
    assert user.email == "owner@example.com"
    assert cabinet.name == "Cabinet Ada"
    assert membership.role == Role.OWNER
    assert membership.user_id == user.pk


@pytest.mark.django_db
def test_invite_and_accept_creates_membership() -> None:
    """Invitation → acceptation crée l'adhésion avec le bon rôle."""
    owner = UserFactory()
    cabinet, _ = create_cabinet_with_owner(owner=owner, name="Dupond & Associés")
    invitation = invite_member(
        cabinet=cabinet,
        email="collab@example.com",
        role=Role.SECRETARY,
        invited_by=owner,
    )
    assert invitation.is_pending

    user, membership, inv = accept_invitation(
        token=invitation.token,
        password="Str0ng-Passw0rd!",
        first_name="Bob",
        last_name="Martin",
    )
    assert user.email == "collab@example.com"
    assert membership.role == Role.SECRETARY
    assert inv.is_accepted
    assert Membership.objects.filter(user=user, cabinet=cabinet, is_active=True).exists()


@pytest.mark.django_db
def test_invite_requires_permission() -> None:
    """Un lecteur ne peut pas inviter."""
    owner = UserFactory()
    cabinet, _ = create_cabinet_with_owner(owner=owner, name="Cab")
    reader = UserFactory()
    MembershipFactory(user=reader, cabinet=cabinet, role=Role.READ_ONLY)

    with pytest.raises(PermissionDenied):
        invite_member(
            cabinet=cabinet,
            email="x@example.com",
            role=Role.ASSOCIATE,
            invited_by=reader,
        )


@pytest.mark.django_db
def test_can_invite_caiman_role() -> None:
    """Le rôle Caïman fait partie des deux rôles disponibles."""
    owner = UserFactory()
    cabinet, _ = create_cabinet_with_owner(owner=owner, name="Cab")
    invitation = invite_member(
        cabinet=cabinet,
        email="x@example.com",
        role=Role.CAIMAN,
        invited_by=owner,
    )
    assert invitation.role == Role.CAIMAN


@pytest.mark.django_db
def test_accept_invitation_email_mismatch() -> None:
    """Un user connecté avec un autre e-mail ne peut pas accepter."""
    invitation = InvitationFactory(email="target@example.com")
    other = UserFactory(email="other@example.com")
    with pytest.raises(ValidationError):
        accept_invitation(token=invitation.token, user=other)


@pytest.mark.django_db
def test_role_permissions_matrix() -> None:
    """La matrice de rôles est cohérente."""
    assert list(Role.choices) == [("caiman", "Caïman"), ("lawyer", "Avocat")]
    assert role_has_perm(Role.OWNER, "manage_cabinet")
    assert not role_has_perm(Role.READ_ONLY, "invite")
    assert role_has_perm(Role.LAWYER, "invite")


@pytest.mark.django_db
def test_user_has_cabinet_perm() -> None:
    """Permission évaluée via membership."""
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.ASSOCIATE)
    assert user_has_cabinet_perm(user=user, cabinet=cabinet, perm="view")
    assert not user_has_cabinet_perm(user=user, cabinet=cabinet, perm="manage_cabinet")


@pytest.mark.django_db
def test_expired_invitation_rejected() -> None:
    """Une invitation expirée est refusée."""
    from datetime import timedelta

    from django.utils import timezone

    invitation = InvitationFactory()
    Invitation.objects.filter(pk=invitation.pk).update(
        expires_at=timezone.now() - timedelta(days=1)
    )
    invitation.refresh_from_db()
    with pytest.raises(ValidationError):
        accept_invitation(token=invitation.token, password="Str0ng-Passw0rd!")
