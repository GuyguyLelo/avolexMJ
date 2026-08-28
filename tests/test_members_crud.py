"""Tests CRUD membres de cabinet."""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.tenants.models import Membership
from apps.tenants.roles import Role
from apps.tenants.services import add_cabinet_member, remove_cabinet_member, update_cabinet_member
from tests.factories import CabinetFactory, MembershipFactory, UserFactory


def _login_with_cabinet(client, user, cabinet) -> None:  # type: ignore[no-untyped-def]
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()


@pytest.mark.django_db
def test_owner_can_add_update_and_remove_member(client) -> None:  # type: ignore[no-untyped-def]
    owner = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    _login_with_cabinet(client, owner, cabinet)

    page = client.get(reverse("tenants:member_list"))
    assert page.status_code == 200
    assert "Nouveau membre" in page.content.decode()

    created = client.post(
        reverse("tenants:member_create"),
        {
            "email": "avocat.nouveau@example.com",
            "first_name": "Aline",
            "last_name": "Mwamba",
            "phone": "+243 810 000 001",
            "role": Role.LAWYER,
        },
    )
    assert created.status_code == 302
    membership = Membership.objects.get(cabinet=cabinet, user__email="avocat.nouveau@example.com")
    assert membership.role == Role.LAWYER
    assert membership.user.phone == "+243 810 000 001"

    updated = client.post(
        reverse("tenants:member_update", args=[membership.pk]),
        {
            "email": "avocat.nouveau@example.com",
            "first_name": "Aline",
            "last_name": "Mwamba",
            "phone": "+243 810 000 002",
            "role": Role.ASSOCIATE,
            "is_active": "on",
        },
    )
    assert updated.status_code == 302
    membership.refresh_from_db()
    assert membership.role == Role.ASSOCIATE
    assert membership.user.phone == "+243 810 000 002"

    removed = client.post(reverse("tenants:member_delete", args=[membership.pk]))
    assert removed.status_code == 302
    assert Membership.objects.filter(pk=membership.pk).exists() is False


@pytest.mark.django_db
def test_lawyer_cannot_manage_members(client) -> None:  # type: ignore[no-untyped-def]
    lawyer = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=lawyer, cabinet=cabinet, role=Role.LAWYER)
    _login_with_cabinet(client, lawyer, cabinet)
    assert client.get(reverse("tenants:member_list")).status_code == 200
    assert client.get(reverse("tenants:member_create")).status_code == 403


@pytest.mark.django_db
def test_cannot_remove_last_owner() -> None:
    owner = UserFactory()
    cabinet = CabinetFactory()
    membership = MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    with pytest.raises(ValidationError):
        remove_cabinet_member(actor=owner, membership=membership)


@pytest.mark.django_db
def test_platform_admin_can_add_member_on_cabinet(client) -> None:  # type: ignore[no-untyped-def]
    admin = UserFactory(is_platform_admin=True)
    cabinet = CabinetFactory()
    MembershipFactory(user=UserFactory(), cabinet=cabinet, role=Role.OWNER)
    client.force_login(admin)
    page = client.get(reverse("tenants:cabinet_detail", args=[cabinet.pk]))
    assert page.status_code == 200
    assert "Nouveau membre" in page.content.decode()
    created = client.post(
        reverse("tenants:cabinet_member_create", args=[cabinet.pk]),
        {
            "email": "secretaire@example.com",
            "first_name": "Nadia",
            "last_name": "Kanda",
            "role": Role.SECRETARY,
        },
    )
    assert created.status_code == 302
    assert Membership.objects.filter(
        cabinet=cabinet, user__email="secretaire@example.com", role=Role.SECRETARY
    ).exists()


@pytest.mark.django_db
def test_regular_user_cannot_add_member_via_service() -> None:
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.ASSOCIATE)
    with pytest.raises(PermissionDenied):
        add_cabinet_member(
            actor=user,
            cabinet=cabinet,
            email="x@example.com",
            role=Role.LAWYER,
        )


@pytest.mark.django_db
def test_update_member_cannot_drop_last_owner() -> None:
    owner = UserFactory()
    cabinet = CabinetFactory()
    membership = MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    with pytest.raises(ValidationError):
        update_cabinet_member(actor=owner, membership=membership, role=Role.LAWYER)
