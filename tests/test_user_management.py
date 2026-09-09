"""Tests gestion des utilisateurs (SuperAdmin)."""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.tenants.roles import Role
from tests.factories import CabinetFactory, MembershipFactory, UserFactory


@pytest.mark.django_db
def test_administrator_cannot_access_user_management(client) -> None:  # type: ignore[no-untyped-def]
    admin = UserFactory(is_platform_admin=True, is_super_admin=False)
    client.force_login(admin)
    assert client.get(reverse("accounts:user_list")).status_code == 403


@pytest.mark.django_db
def test_cabinet_user_cannot_access_user_management(client) -> None:  # type: ignore[no-untyped-def]
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.LAWYER)
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()
    assert client.get(reverse("accounts:user_list")).status_code == 403


@pytest.mark.django_db
def test_super_admin_manages_users(client) -> None:  # type: ignore[no-untyped-def]
    super_admin = UserFactory(
        is_super_admin=True,
        is_platform_admin=True,
        email="SuperAdmin",
    )
    client.force_login(super_admin)

    listing = client.get(reverse("accounts:user_list"))
    assert listing.status_code == 200
    assert b"Utilisateurs" in listing.content

    create = client.post(
        reverse("accounts:user_create"),
        {
            "email": "admin-mj@avolex.local",
            "first_name": "Min",
            "last_name": "Justice",
            "phone": "+243800000001",
            "password": "Str0ng-Passw0rd!",
            "password_confirm": "Str0ng-Passw0rd!",
            "account_type": "administrator",
            "is_active": "on",
        },
    )
    assert create.status_code == 302
    user = User.objects.get(email="admin-mj@avolex.local")
    assert user.is_platform_admin is True
    assert user.is_super_admin is False

    cabinet_user = client.post(
        reverse("accounts:user_create"),
        {
            "email": "cabinet@avolex.local",
            "first_name": "Ca",
            "last_name": "Binet",
            "password": "Str0ng-Passw0rd!",
            "password_confirm": "Str0ng-Passw0rd!",
            "account_type": "cabinet",
            "cabinet": str(CabinetFactory().pk),
            "cabinet_role": Role.LAWYER,
            "is_active": "on",
        },
    )
    assert cabinet_user.status_code == 302
    cab = User.objects.get(email="cabinet@avolex.local")
    assert cab.is_platform_admin is False
    assert cab.is_super_admin is False
    from apps.tenants.models import Membership

    assert Membership.objects.filter(user=cab, is_active=True).count() == 1

    missing_cabinet = client.post(
        reverse("accounts:user_create"),
        {
            "email": "sans-cabinet@avolex.local",
            "password": "Str0ng-Passw0rd!",
            "password_confirm": "Str0ng-Passw0rd!",
            "account_type": "cabinet",
            "is_active": "on",
        },
    )
    assert missing_cabinet.status_code == 200
    assert not User.objects.filter(email="sans-cabinet@avolex.local").exists()

    deactivate = client.post(reverse("accounts:user_deactivate", args=[cab.pk]))
    assert deactivate.status_code == 302
    cab.refresh_from_db()
    assert cab.is_active is False


@pytest.mark.django_db
def test_super_admin_and_admin_have_no_cabinet_membership(client) -> None:  # type: ignore[no-untyped-def]
    from apps.tenants.models import Membership

    super_admin = UserFactory(
        is_super_admin=True,
        is_platform_admin=True,
        email="SuperAdmin",
    )
    client.force_login(super_admin)

    create_admin = client.post(
        reverse("accounts:user_create"),
        {
            "email": "AdminMJ",
            "first_name": "Admin",
            "last_name": "MJ",
            "password": "Str0ng-Passw0rd!",
            "password_confirm": "Str0ng-Passw0rd!",
            "account_type": "administrator",
            "is_active": "on",
        },
    )
    assert create_admin.status_code == 302
    admin = User.objects.get(email="AdminMJ")
    assert admin.is_platform_admin is True
    assert Membership.objects.filter(user=admin, is_active=True).count() == 0

    create_super = client.post(
        reverse("accounts:user_create"),
        {
            "email": "AutreSuper",
            "password": "Str0ng-Passw0rd!",
            "password_confirm": "Str0ng-Passw0rd!",
            "account_type": "superadmin",
            "is_active": "on",
        },
    )
    assert create_super.status_code == 302
    other = User.objects.get(email="AutreSuper")
    assert other.is_super_admin is True
    assert Membership.objects.filter(user=other, is_active=True).count() == 0


@pytest.mark.django_db
def test_promote_to_admin_detaches_cabinet_membership(client) -> None:  # type: ignore[no-untyped-def]
    from apps.tenants.models import Membership

    super_admin = UserFactory(is_super_admin=True, is_platform_admin=True, email="SuperAdmin")
    lawyer = UserFactory(email="avocat-promo@avolex.local")
    cabinet = CabinetFactory()
    MembershipFactory(user=lawyer, cabinet=cabinet, role=Role.LAWYER)
    # Un autre Caïman pour ne pas bloquer si besoin
    MembershipFactory(user=UserFactory(email="caiman@avolex.local"), cabinet=cabinet, role=Role.CAIMAN)

    client.force_login(super_admin)
    resp = client.post(
        reverse("accounts:user_update", args=[lawyer.pk]),
        {
            "email": lawyer.email,
            "first_name": lawyer.first_name,
            "last_name": lawyer.last_name,
            "account_type": "administrator",
            "is_active": "on",
        },
    )
    assert resp.status_code == 302
    lawyer.refresh_from_db()
    assert lawyer.is_platform_admin is True
    assert Membership.objects.filter(user=lawyer, is_active=True).count() == 0


@pytest.mark.django_db
def test_cannot_attach_admin_as_cabinet_owner() -> None:
    from django.core.exceptions import ValidationError

    from apps.tenants.services import create_cabinet_as_platform_admin

    actor = UserFactory(is_super_admin=True, is_platform_admin=True, email="SuperAdmin")
    admin = UserFactory(is_platform_admin=True, is_super_admin=False, email="Admin")
    with pytest.raises(ValidationError):
        create_cabinet_as_platform_admin(
            actor=actor,
            name="Cabinet interdit",
            owner_email="Admin",
        )


@pytest.mark.django_db
def test_cannot_deactivate_last_super_admin(client) -> None:  # type: ignore[no-untyped-def]
    super_admin = UserFactory(
        is_super_admin=True,
        is_platform_admin=True,
        email="seul-super",
    )
    client.force_login(super_admin)
    resp = client.post(reverse("accounts:user_deactivate", args=[super_admin.pk]))
    assert resp.status_code == 302
    super_admin.refresh_from_db()
    assert super_admin.is_active is True
