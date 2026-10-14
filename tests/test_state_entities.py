"""Tests du référentiel des entités étatiques RDC."""

from __future__ import annotations

import pytest
from django.urls import reverse

from apps.tenants.models import StateEntity
from apps.tenants.roles import Role
from apps.tenants.state_entities import ensure_default_state_entities
from tests.factories import CabinetFactory, MembershipFactory, UserFactory


def _login_with_cabinet(client, user, cabinet) -> None:  # type: ignore[no-untyped-def]
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()


@pytest.mark.django_db
def test_platform_admin_manages_state_entity_catalog(client) -> None:  # type: ignore[no-untyped-def]
    admin = UserFactory(is_platform_admin=True)
    client.force_login(admin)
    listing = client.get(reverse("tenants:state_entity_list"))
    assert listing.status_code == 200
    html = listing.content.decode()
    assert "Entités étatiques" in html
    assert "Ministère de la Justice et Garde des Sceaux" in html

    created = client.post(
        reverse("tenants:state_entity_create"),
        {
            "name": "Office national de test",
            "category": "Entités publiques",
            "is_active": "on",
        },
    )
    assert created.status_code == 302
    item = StateEntity.objects.get(name="Office national de test")
    assert item.category == "Entités publiques"
    updated = client.post(
        reverse("tenants:state_entity_update", args=[item.pk]),
        {
            "name": "Office national de test",
            "category": "Institutions constitutionnelles",
            "is_active": "on",
        },
    )
    assert updated.status_code == 302
    item.refresh_from_db()
    assert item.category == "Institutions constitutionnelles"
    deleted = client.post(reverse("tenants:state_entity_delete", args=[item.pk]))
    assert deleted.status_code == 302
    assert StateEntity.objects.filter(pk=item.pk).exists() is False


@pytest.mark.django_db
def test_cabinet_cannot_access_state_entity_catalog(client) -> None:  # type: ignore[no-untyped-def]
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    _login_with_cabinet(client, user, cabinet)
    assert client.get(reverse("tenants:state_entity_list")).status_code == 403


@pytest.mark.django_db
def test_ensure_default_state_entities() -> None:
    items = ensure_default_state_entities()
    assert len(items) >= 40
    assert StateEntity.objects.filter(name="République Démocratique du Congo").exists()
    assert StateEntity.objects.filter(
        name="Ministère de la Justice et Garde des Sceaux", category="Ministères"
    ).exists()
    assert StateEntity.objects.filter(name="Province de Kinshasa").exists()
