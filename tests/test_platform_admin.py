"""Tests administrateur plateforme / supervision."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.calendar_app.models import EventType
from apps.calendar_app.services import create_event
from apps.clients.models import Client, ClientType
from apps.clients.services import create_client
from apps.core.dashboard import build_cabinet_charts, build_platform_charts
from apps.matters.models import Matter, MatterScale, MatterStatus
from apps.matters.services import create_matter
from apps.tenants.context import cabinet_context
from apps.tenants.roles import PERM_ADD, PERM_VIEW, Role
from apps.tenants.services import is_platform_admin, list_user_cabinets, user_has_cabinet_perm
from tests.factories import CabinetFactory, MembershipFactory, UserFactory


@pytest.mark.django_db
def test_platform_admin_sees_all_cabinets() -> None:
    admin = UserFactory(is_platform_admin=True)
    c1 = CabinetFactory(name="Alpha Law")
    c2 = CabinetFactory(name="Beta Law")
    MembershipFactory(user=UserFactory(), cabinet=c1, role=Role.OWNER)
    MembershipFactory(user=UserFactory(), cabinet=c2, role=Role.OWNER)

    cabinets = list_user_cabinets(admin)
    names = {c.name for c in cabinets}
    assert "Alpha Law" in names
    assert "Beta Law" in names
    assert is_platform_admin(admin)


@pytest.mark.django_db
def test_platform_admin_has_no_current_cabinet() -> None:
    """Un compte ministère n'est jamais rattaché à un cabinet courant."""
    from django.core.exceptions import PermissionDenied
    from django.test import RequestFactory

    from apps.tenants.services import resolve_cabinet_for_request, switch_cabinet

    admin = UserFactory(is_platform_admin=True)
    CabinetFactory(name="Alpha Law")
    request = RequestFactory().get("/")
    request.user = admin
    request.session = {}
    assert resolve_cabinet_for_request(request) is None
    with pytest.raises(PermissionDenied):
        switch_cabinet(request=request, user=admin, cabinet_id=str(CabinetFactory().pk))


@pytest.mark.django_db
def test_platform_admin_read_only_perms() -> None:
    admin = UserFactory(is_platform_admin=True)
    cabinet = CabinetFactory()
    assert user_has_cabinet_perm(user=admin, cabinet=cabinet, perm=PERM_VIEW) is True
    assert user_has_cabinet_perm(user=admin, cabinet=cabinet, perm=PERM_ADD) is False


@pytest.mark.django_db
def test_supervision_page(client) -> None:  # type: ignore[no-untyped-def]
    admin = UserFactory(is_platform_admin=True)
    cabinet = CabinetFactory(name="ILEO Law Firm")
    owner = UserFactory()
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)

    with cabinet_context(cabinet):
        cl = create_client(
            cabinet=cabinet,
            user=owner,
            client_type=ClientType.PERSON,
            last_name="Kabasele",
        )
        matter = create_matter(
            user=admin,
            title="Affaire commerciale",
        )
        from apps.procurations.services import stamp_granted_procuration

        stamp_granted_procuration(matter=matter, cabinet=cabinet, actor=admin)
        create_event(
            cabinet=cabinet,
            user=owner,
            title="Audience TGI Gombe",
            starts_at=timezone.now() + timedelta(days=2),
            event_type=EventType.HEARING,
            matter=matter,
            court="Tribunal de grande instance de Kinshasa/Gombe",
        )

    client.force_login(admin)
    resp = client.get(reverse("core:supervision"))
    assert resp.status_code == 200
    assert b"ILEO Law Firm" in resp.content
    assert b"Supervision nationale" in resp.content
    assert b"Audience TGI Gombe" in resp.content
    assert b"page-header-dash--ministry" in resp.content
    assert b"app-cabinet-banner" in resp.content
    assert b"app-cabinet-banner--ministry" in resp.content
    assert b"matters_by_cabinet" in resp.content
    assert b"supervision-charts-data" in resp.content
    assert b"Dossiers actifs par cabinet" in resp.content


@pytest.mark.django_db
def test_build_platform_charts_includes_cabinet_series() -> None:
    cabinet = CabinetFactory(name="ILEO Law Firm")
    owner = UserFactory()
    admin = UserFactory(is_platform_admin=True)
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)

    with cabinet_context(cabinet):
        cl = create_client(
            cabinet=cabinet,
            user=owner,
            client_type=ClientType.PERSON,
            last_name="Kabasele",
        )
        matter = create_matter(
            user=admin,
            title="Affaire commerciale",
        )
        from apps.procurations.services import stamp_granted_procuration

        stamp_granted_procuration(matter=matter, cabinet=cabinet, actor=admin)

    charts = build_platform_charts()
    labels = {row["label"] for row in charts["matters_by_cabinet"]}
    assert "ILEO Law Firm" in labels
    assert any(row["key"] == "granted" for row in charts["procurations_by_status"])
    assert charts["matters_by_scale"]


@pytest.mark.django_db
def test_build_cabinet_charts_includes_status_series() -> None:
    cabinet = CabinetFactory(name="ILEO Law Firm")
    owner = UserFactory()
    admin = UserFactory(is_platform_admin=True)
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)

    with cabinet_context(cabinet):
        cl = create_client(
            cabinet=cabinet,
            user=owner,
            client_type=ClientType.PERSON,
            last_name="Kabasele",
        )
        create_matter(
            user=admin,
            title="Affaire commerciale",
        )
        from apps.procurations.services import stamp_granted_procuration

        matter = Matter.unscoped.get(title="Affaire commerciale")
        stamp_granted_procuration(matter=matter, cabinet=cabinet, actor=admin)
        charts = build_cabinet_charts(cabinet=cabinet)

    keys = {row["key"] for row in charts["matters_by_status"]}
    assert "open" in keys or "in_progress" in keys
    assert len(charts["activity_by_month"]) == 6
    assert len(charts["revenue_by_month"]) == 6


@pytest.mark.django_db
def test_regular_user_cannot_access_supervision(client) -> None:  # type: ignore[no-untyped-def]
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.LAWYER)
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()
    resp = client.get(reverse("core:supervision"))
    assert resp.status_code == 403


@pytest.mark.django_db
def test_platform_admin_can_create_matter(client) -> None:  # type: ignore[no-untyped-def]
    """Le ministère peut ouvrir un dossier pour le cabinet sélectionné."""
    admin = UserFactory(is_platform_admin=True)
    owner = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    with cabinet_context(cabinet):
        person = create_client(
            cabinet=cabinet,
            user=owner,
            client_type=ClientType.PERSON,
            last_name="Ilunga",
        )

    client.force_login(admin)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()

    page = client.get(reverse("matters:create"))
    assert page.status_code == 200
    assert "Nouveau dossier" in page.content.decode()

    created = client.post(
        reverse("matters:create"),
        {
            "title": "Affaire ouverte par le ministère",
            "scale": MatterScale.NATIONAL,
            "jurisdiction": "Tribunal de grande instance de Kinshasa/Gombe",
            "status": MatterStatus.OPEN,
            "form-TOTAL_FORMS": "0",
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
        },
    )
    assert created.status_code == 302
    matter = Matter.unscoped.get(title="Affaire ouverte par le ministère")
    assert matter.cabinet_id is None
    pk = matter.pk

    assert client.get(reverse("matters:update", args=[pk])).status_code == 200


@pytest.mark.django_db
def test_platform_admin_can_create_client(client) -> None:  # type: ignore[no-untyped-def]
    """Le ministère peut créer un justiciable pour le cabinet sélectionné."""
    admin = UserFactory(is_platform_admin=True)
    owner = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    client.force_login(admin)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()

    page = client.get(reverse("clients:create"))
    assert page.status_code == 200

    created = client.post(
        reverse("clients:create"),
        {
            "client_type": ClientType.PERSON,
            "last_name": "Mbala",
            "first_name": "Grace",
            "country": "CD",
        },
    )
    assert created.status_code == 302
    with cabinet_context(cabinet):
        person = Client.objects.get(last_name="Mbala")
        assert person.cabinet_id == cabinet.pk
        pk = person.pk
    assert client.get(reverse("clients:update", args=[pk])).status_code == 403
