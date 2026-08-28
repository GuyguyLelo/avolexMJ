"""Tests matières juridiques, spécialités et suggestion de cabinets."""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.clients.models import ClientType
from apps.clients.services import create_client
from apps.matters.models import Matter, MatterScale, MatterStatus
from apps.tenants.context import cabinet_context
from apps.tenants.legal_areas import ensure_default_legal_practice_areas
from apps.tenants.models import CabinetPracticeArea, LegalPracticeArea
from apps.tenants.roles import Role
from apps.tenants.services import (
    add_cabinet_practice_area,
    suggest_cabinets_for_practice_area,
)
from tests.factories import (
    CabinetFactory,
    CabinetPracticeAreaFactory,
    LegalPracticeAreaFactory,
    MembershipFactory,
    UserFactory,
)


def _login_with_cabinet(client, user, cabinet) -> None:  # type: ignore[no-untyped-def]
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()


@pytest.mark.django_db
def test_platform_admin_manages_practice_area_catalog(client) -> None:  # type: ignore[no-untyped-def]
    admin = UserFactory(is_platform_admin=True)
    client.force_login(admin)
    listing = client.get(reverse("tenants:practice_area_list"))
    assert listing.status_code == 200
    assert "Matières juridiques" in listing.content.decode()

    created = client.post(
        reverse("tenants:practice_area_create"),
        {"name": "Droit douanier", "description": "Contentieux douanier", "is_active": "on"},
    )
    assert created.status_code == 302
    area = LegalPracticeArea.objects.get(name="Droit douanier")
    updated = client.post(
        reverse("tenants:practice_area_update", args=[area.pk]),
        {"name": "Droit douanier", "description": "Mis à jour", "is_active": "on"},
    )
    assert updated.status_code == 302
    area.refresh_from_db()
    assert area.description == "Mis à jour"


@pytest.mark.django_db
def test_cabinet_owner_manages_specialties(client) -> None:  # type: ignore[no-untyped-def]
    owner = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    area = LegalPracticeAreaFactory(name="Droit minier")
    _login_with_cabinet(client, owner, cabinet)

    page = client.get(reverse("tenants:specialty_list"))
    assert page.status_code == 200
    added = client.post(
        reverse("tenants:specialty_list"),
        {"practice_area": str(area.pk)},
    )
    assert added.status_code == 302
    link = CabinetPracticeArea.objects.get(cabinet=cabinet, practice_area=area)
    removed = client.post(reverse("tenants:specialty_remove", args=[link.pk]))
    assert removed.status_code == 302
    assert CabinetPracticeArea.objects.filter(pk=link.pk).exists() is False


@pytest.mark.django_db
def test_suggest_cabinets_for_practice_area() -> None:
    area = LegalPracticeAreaFactory(name="Droit OHADA")
    specialized = CabinetFactory(name="Cabinet OHADA", city="Gombe")
    other = CabinetFactory(name="Cabinet civil")
    CabinetPracticeAreaFactory(cabinet=specialized, practice_area=area)
    CabinetPracticeAreaFactory(
        cabinet=other,
        practice_area=LegalPracticeAreaFactory(name="Droit civil"),
    )
    names = list(
        suggest_cabinets_for_practice_area(practice_area_name="Droit OHADA").values_list(
            "name", flat=True
        )
    )
    assert "Cabinet OHADA" in names
    assert "Cabinet civil" not in names


@pytest.mark.django_db
def test_matter_create_proposes_specialized_cabinets(client) -> None:  # type: ignore[no-untyped-def]
    admin = UserFactory(is_platform_admin=True)
    owner = UserFactory()
    cabinet = CabinetFactory(name="ILEO Spécialisé", city="Kinshasa")
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    area = LegalPracticeAreaFactory(name="Droit du travail")
    add_cabinet_practice_area(actor=admin, cabinet=cabinet, practice_area=area)
    with cabinet_context(cabinet):
        person = create_client(
            cabinet=cabinet,
            user=owner,
            client_type=ClientType.PERSON,
            last_name="Kalala",
        )

    _login_with_cabinet(client, admin, cabinet)
    page = client.get(reverse("matters:create"), {"practice_area": "Droit du travail"})
    html = page.content.decode()
    assert page.status_code == 200
    assert "Cabinets spécialisés dans cette matière" in html
    assert "ILEO Spécialisé" in html

    created = client.post(
        reverse("matters:create"),
        {
            "practice_area": "Droit du travail",
            "target_cabinet": str(cabinet.pk),
            "client": str(person.pk),
            "title": "Licenciement abusif",
            "scale": MatterScale.NATIONAL,
            "status": MatterStatus.OPEN,
            "responsible_lawyer": str(owner.pk),
        },
    )
    assert created.status_code == 302
    with cabinet_context(cabinet):
        matter = Matter.objects.get(title="Licenciement abusif")
        assert matter.practice_area == "Droit du travail"
        assert matter.cabinet_id == cabinet.pk


@pytest.mark.django_db
def test_ministry_must_choose_cabinet_when_creating_matter(client) -> None:  # type: ignore[no-untyped-def]
    admin = UserFactory(is_platform_admin=True)
    owner = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    with cabinet_context(cabinet):
        person = create_client(
            cabinet=cabinet,
            user=owner,
            client_type=ClientType.PERSON,
            last_name="Mwamba",
        )

    _login_with_cabinet(client, admin, cabinet)
    response = client.post(
        reverse("matters:create"),
        {
            "client": str(person.pk),
            "title": "Dossier sans cabinet",
            "scale": MatterScale.NATIONAL,
            "status": MatterStatus.OPEN,
            "responsible_lawyer": str(owner.pk),
        },
    )

    assert response.status_code == 200
    assert "Ce champ est obligatoire" in response.content.decode()
    with cabinet_context(cabinet):
        assert not Matter.objects.filter(title="Dossier sans cabinet").exists()


@pytest.mark.django_db
def test_matter_create_context_json(client) -> None:  # type: ignore[no-untyped-def]
    admin = UserFactory(is_platform_admin=True)
    owner = UserFactory()
    cabinet = CabinetFactory(name="Cabinet Suggest")
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    area = LegalPracticeAreaFactory(name="Droit fiscal")
    add_cabinet_practice_area(actor=admin, cabinet=cabinet, practice_area=area)
    _login_with_cabinet(client, admin, cabinet)
    resp = client.get(
        reverse("matters:create_context"),
        {"practice_area": "Droit fiscal", "cabinet": str(cabinet.pk)},
    )
    assert resp.status_code == 200
    payload = resp.json()
    names = [item["name"] for item in payload["suggested_cabinets"]]
    assert "Cabinet Suggest" in names
    assert any(item["id"] == str(owner.pk) for item in payload["lawyers"])


@pytest.mark.django_db
def test_cabinet_cannot_access_practice_area_catalog(client) -> None:  # type: ignore[no-untyped-def]
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    _login_with_cabinet(client, user, cabinet)
    assert client.get(reverse("tenants:practice_area_list")).status_code == 403


@pytest.mark.django_db
def test_ensure_default_legal_practice_areas() -> None:
    areas = ensure_default_legal_practice_areas()
    assert len(areas) >= 10
    assert LegalPracticeArea.objects.filter(name="Droit commercial").exists()
