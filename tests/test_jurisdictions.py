"""Tests du référentiel de juridictions."""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.tenants.jurisdictions import ensure_default_jurisdictions
from apps.tenants.models import Jurisdiction, JurisdictionScale
from apps.tenants.roles import Role
from tests.factories import CabinetFactory, MembershipFactory, UserFactory


def _login_with_cabinet(client, user, cabinet) -> None:  # type: ignore[no-untyped-def]
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()


@pytest.mark.django_db
def test_platform_admin_manages_jurisdiction_catalog(client) -> None:  # type: ignore[no-untyped-def]
    admin = UserFactory(is_platform_admin=True)
    client.force_login(admin)
    listing = client.get(reverse("tenants:jurisdiction_list"))
    assert listing.status_code == 200
    html = listing.content.decode()
    assert "Juridictions" in html
    assert "Cour de cassation" in html

    created = client.post(
        reverse("tenants:jurisdiction_create"),
        {
            "name": "Tribunal spécial de test",
            "scale": JurisdictionScale.NATIONAL,
            "category": "Tribunaux spécialisés",
            "is_active": "on",
        },
    )
    assert created.status_code == 302
    item = Jurisdiction.objects.get(name="Tribunal spécial de test")
    assert item.scale == JurisdictionScale.NATIONAL
    updated = client.post(
        reverse("tenants:jurisdiction_update", args=[item.pk]),
        {
            "name": "Tribunal spécial de test",
            "scale": JurisdictionScale.INTERNATIONAL,
            "category": "Cours internationales",
            "is_active": "on",
        },
    )
    assert updated.status_code == 302
    item.refresh_from_db()
    assert item.scale == JurisdictionScale.INTERNATIONAL
    deleted = client.post(reverse("tenants:jurisdiction_delete", args=[item.pk]))
    assert deleted.status_code == 302
    assert Jurisdiction.objects.filter(pk=item.pk).exists() is False


@pytest.mark.django_db
def test_cabinet_cannot_access_jurisdiction_catalog(client) -> None:  # type: ignore[no-untyped-def]
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    _login_with_cabinet(client, user, cabinet)
    assert client.get(reverse("tenants:jurisdiction_list")).status_code == 403


@pytest.mark.django_db
def test_ensure_default_jurisdictions() -> None:
    items = ensure_default_jurisdictions()
    assert len(items) >= 10
    assert Jurisdiction.objects.filter(name="Cour de cassation").exists()
    assert Jurisdiction.objects.filter(
        name="Cour pénale internationale", scale=JurisdictionScale.INTERNATIONAL
    ).exists()
