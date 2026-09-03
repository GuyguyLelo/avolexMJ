"""Tests CRUD cabinets avocats (supervision plateforme)."""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from apps.tenants.models import Cabinet, Membership
from apps.tenants.roles import Role
from apps.tenants.services import (
    create_cabinet_as_platform_admin,
    delete_cabinet_as_platform_admin,
    update_cabinet_as_platform_admin,
)
from tests.factories import CabinetFactory, MembershipFactory, UserFactory


@pytest.mark.django_db
def test_platform_admin_creates_cabinet_with_new_owner() -> None:
    admin = UserFactory(is_platform_admin=True)
    cabinet, membership, owner = create_cabinet_as_platform_admin(
        actor=admin,
        name="Cabinet Mbala",
        owner_email="mbala@example.com",
        owner_first_name="Jean",
        owner_last_name="Mbala",
        city="Kinshasa",
        country="CD",
    )
    assert cabinet.name == "Cabinet Mbala"
    assert cabinet.city == "Kinshasa"
    assert cabinet.is_active is True
    assert owner.email == "mbala@example.com"
    assert membership.role == Role.OWNER
    assert membership.user_id == owner.pk
    assert owner.has_usable_password() is False


@pytest.mark.django_db
def test_platform_admin_attaches_existing_user_as_owner() -> None:
    admin = UserFactory(is_platform_admin=True)
    existing = UserFactory(email="associe@example.com", first_name="Léa")
    cabinet, membership, owner = create_cabinet_as_platform_admin(
        actor=admin,
        name="Cabinet Kivu",
        owner_email="associe@example.com",
    )
    assert owner.pk == existing.pk
    assert membership.cabinet_id == cabinet.pk
    assert membership.role == Role.OWNER


@pytest.mark.django_db
def test_regular_user_cannot_create_cabinet() -> None:
    user = UserFactory()
    with pytest.raises(PermissionDenied):
        create_cabinet_as_platform_admin(
            actor=user,
            name="Illégal",
            owner_email="x@example.com",
        )


@pytest.mark.django_db
def test_platform_admin_updates_and_deletes_cabinet() -> None:
    admin = UserFactory(is_platform_admin=True)
    cabinet = CabinetFactory(name="Ancien nom", city="Gombe")
    updated = update_cabinet_as_platform_admin(
        actor=admin,
        cabinet=cabinet,
        name="Nouveau nom",
        city="Limete",
    )
    assert updated.name == "Nouveau nom"
    assert updated.city == "Limete"

    delete_cabinet_as_platform_admin(actor=admin, cabinet=cabinet)
    deleted = Cabinet.all_objects.get(pk=cabinet.pk)
    assert deleted.is_active is False
    assert deleted.is_deleted is True
    assert Cabinet.objects.filter(pk=cabinet.pk).exists() is False


@pytest.mark.django_db
def test_cabinet_list_page(client) -> None:  # type: ignore[no-untyped-def]
    admin = UserFactory(is_platform_admin=True)
    CabinetFactory(name="ILEO Law Firm")
    client.force_login(admin)
    resp = client.get(reverse("tenants:cabinet_list"))
    assert resp.status_code == 200
    assert b"ILEO Law Firm" in resp.content
    assert b"Cabinets avocats" in resp.content


@pytest.mark.django_db
def test_cabinet_crud_http(client) -> None:  # type: ignore[no-untyped-def]
    admin = UserFactory(is_platform_admin=True)
    client.force_login(admin)

    create_page = client.get(reverse("tenants:cabinet_create"))
    assert create_page.status_code == 200
    assert "Paramètres" not in create_page.content.decode()
    assert "Confirmation du mot de passe" not in create_page.content.decode()
    assert b"Ajouter un membre" in create_page.content

    create_resp = client.post(
        reverse("tenants:cabinet_create"),
        {
            "name": "Cabinet Gombe",
            "legal_name": "Cabinet Gombe SPRL",
            "contract_number": "CTR-2026-001",
            "bar_association": "Barreau de Kinshasa/Gombe",
            "owner_email": "gombe-owner@example.com",
            "owner_first_name": "Paul",
            "owner_last_name": "Nsimba",
        },
    )
    assert create_resp.status_code == 302
    cabinet = Cabinet.objects.get(name="Cabinet Gombe")
    assert cabinet.is_active is True
    assert cabinet.contract_number == "CTR-2026-001"
    assert cabinet.default_currency == "USD"
    assert Membership.objects.filter(
        cabinet=cabinet, role=Role.OWNER, user__email="gombe-owner@example.com"
    ).exists()

    detail = client.get(reverse("tenants:cabinet_detail", args=[cabinet.pk]))
    assert detail.status_code == 200
    assert b"Cabinet Gombe" in detail.content

    update_resp = client.post(
        reverse("tenants:cabinet_update", args=[cabinet.pk]),
        {
            "name": "Cabinet Gombe Majeur",
            "legal_name": "Cabinet Gombe SPRL",
            "is_active": "on",
        },
    )
    assert update_resp.status_code == 302
    cabinet.refresh_from_db()
    assert cabinet.name == "Cabinet Gombe Majeur"

    delete_resp = client.post(reverse("tenants:cabinet_delete", args=[cabinet.pk]))
    assert delete_resp.status_code == 302
    assert Cabinet.objects.filter(pk=cabinet.pk).exists() is False


@pytest.mark.django_db
def test_regular_user_cannot_access_cabinet_module(client) -> None:  # type: ignore[no-untyped-def]
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.LAWYER)
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()
    assert client.get(reverse("tenants:cabinet_list")).status_code == 403
    assert client.get(reverse("tenants:cabinet_create")).status_code == 403
    assert client.get(reverse("tenants:cabinet_detail", args=[cabinet.pk])).status_code == 403


@pytest.mark.django_db
def test_platform_admin_uploads_cabinet_contract(client) -> None:  # type: ignore[no-untyped-def]
    from django.core.files.uploadedfile import SimpleUploadedFile

    admin = UserFactory(is_platform_admin=True)
    client.force_login(admin)
    pdf = SimpleUploadedFile("contrat-cabinet.pdf", b"%PDF-1.4 test", content_type="application/pdf")

    resp = client.post(
        reverse("tenants:cabinet_create"),
        {
            "name": "Cabinet Contrat",
            "contract_number": "CTR-FILE-001",
            "bar_association": "Barreau de Kinshasa/Gombe",
            "owner_email": "caiman-contrat@example.com",
            "contract_file": pdf,
        },
    )
    assert resp.status_code == 302
    cabinet = Cabinet.objects.get(name="Cabinet Contrat")
    assert cabinet.contract_file
    assert cabinet.contract_file_name == "contrat-cabinet.pdf"
    assert cabinet.contract_can_preview is True

    detail = client.get(reverse("tenants:cabinet_detail", args=[cabinet.pk]))
    assert detail.status_code == 200
    assert b"contrat-cabinet.pdf" in detail.content
    assert b"Voir le contrat" in detail.content

    download = client.get(reverse("tenants:cabinet_contract_download", args=[cabinet.pk]))
    assert download.status_code == 200
    assert download["Content-Type"] == "application/pdf"

    preview = client.get(reverse("tenants:cabinet_contract_preview", args=[cabinet.pk]))
    assert preview.status_code == 200
    assert preview["Content-Type"] == "application/pdf"

    edit = client.get(reverse("tenants:cabinet_update", args=[cabinet.pk]))
    assert edit.status_code == 200
    assert b"contrat-cabinet.pdf" in edit.content


@pytest.mark.django_db
def test_platform_admin_creates_cabinet_with_extra_members(client) -> None:  # type: ignore[no-untyped-def]
    admin = UserFactory(is_platform_admin=True)
    client.force_login(admin)

    resp = client.post(
        reverse("tenants:cabinet_create"),
        {
            "name": "Cabinet Équipe",
            "contract_number": "CTR-2026-EQ",
            "owner_email": "caiman@example.com",
            "owner_first_name": "Caï",
            "owner_last_name": "Man",
            "extra_member_email": ["avocat1@example.com", "avocat2@example.com"],
            "extra_member_first_name": ["Alice", "Bob"],
            "extra_member_last_name": ["Mukendi", "Kabongo"],
            "extra_member_phone": ["+243 800 111", ""],
            "extra_member_role": ["lawyer", "lawyer"],
        },
    )
    assert resp.status_code == 302
    cabinet = Cabinet.objects.get(name="Cabinet Équipe")
    assert Membership.objects.filter(cabinet=cabinet, is_active=True).count() == 3
    assert Membership.objects.filter(
        cabinet=cabinet, role=Role.CAIMAN, user__email="caiman@example.com"
    ).exists()
    assert Membership.objects.filter(
        cabinet=cabinet, role=Role.LAWYER, user__email="avocat1@example.com"
    ).exists()
    assert Membership.objects.filter(
        cabinet=cabinet, role=Role.LAWYER, user__email="avocat2@example.com"
    ).exists()
