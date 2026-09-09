"""Tests clients / dossiers / agenda / dashboard."""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.calendar_app.models import EventType
from apps.calendar_app.services import create_event
from apps.clients.models import ClientType
from apps.clients.services import create_client
from apps.core.dashboard import build_dashboard_stats
from apps.matters.forms import MatterForm
from apps.matters.models import MatterScale, MatterStatus
from apps.matters.services import archive_matter, create_matter, soft_delete_matter, update_matter
from apps.tenants.context import cabinet_context
from apps.tenants.roles import Role
from tests.factories import CabinetFactory, MembershipFactory, UserFactory


def _open_matter(cabinet, user, client, title: str, **kwargs):  # type: ignore[no-untyped-def]
    """Crée un dossier de test puis le rattache au cabinet via procuration."""
    from apps.procurations.services import stamp_granted_procuration

    actor = (
        user if getattr(user, "is_platform_admin", False) else UserFactory(is_platform_admin=True)
    )
    with_procuration = kwargs.pop("with_procuration", True)
    matter = create_matter(
        user=actor,
        title=title,
        **kwargs,
    )
    if with_procuration:
        stamp_granted_procuration(matter=matter, cabinet=cabinet, actor=actor)
        matter.refresh_from_db()
    return matter


@pytest.mark.django_db
def test_client_matter_flow_and_history() -> None:
    """Création client + dossier + entrée d'historique."""
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    with cabinet_context(cabinet):
        client = create_client(
            cabinet=cabinet,
            user=user,
            client_type=ClientType.PERSON,
            first_name="Ada",
            last_name="Lovelace",
            email="ada@example.com",
        )
        matter = _open_matter(cabinet, user, client, "Affaire test", practice_area="Civil")
        assert matter.reference.startswith("DOS-")
        assert matter.actions.filter(action="created").exists()
        stats = build_dashboard_stats(cabinet=cabinet)
        assert stats.matters_active == 1
        assert stats.matters_total == 1


@pytest.mark.django_db
def test_clients_list_http(client) -> None:  # type: ignore[no-untyped-def]
    """Liste clients accessible au membre."""
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.LAWYER)
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()
    with cabinet_context(cabinet):
        create_client(
            cabinet=cabinet,
            user=user,
            client_type=ClientType.PERSON,
            first_name="Bob",
            last_name="Martin",
        )
    resp = client.get(reverse("clients:list"))
    assert resp.status_code == 200
    assert b"Martin" in resp.content


@pytest.mark.django_db
def test_calendar_event_and_api(client) -> None:  # type: ignore[no-untyped-def]
    """Événement agenda + endpoint API clients."""
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()
    with cabinet_context(cabinet):
        event = create_event(
            cabinet=cabinet,
            user=user,
            title="RDV client",
            starts_at=timezone.now(),
            event_type=EventType.APPOINTMENT,
        )
    resp = client.get(reverse("calendar:list"))
    assert resp.status_code == 200
    assert b"RDV client" in resp.content
    detail = client.get(reverse("calendar:event_detail", kwargs={"pk": event.pk}))
    assert detail.status_code == 200
    assert b"RDV client" in detail.content
    api = client.get("/api/v1/clients/")
    assert api.status_code == 200


@pytest.mark.django_db
def test_closed_matter_cannot_be_deleted_but_can_be_archived() -> None:
    """Un dossier clos est archivable, pas supprimable."""
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    with cabinet_context(cabinet):
        client = create_client(
            cabinet=cabinet,
            user=user,
            client_type=ClientType.PERSON,
            first_name="Claire",
            last_name="Arch",
        )
        matter = _open_matter(cabinet, user, client, "Affaire close")
        admin = UserFactory(is_platform_admin=True)
        update_matter(
            matter=matter,
            user=admin,
            status=MatterStatus.CLOSED,
        )
        matter.refresh_from_db()
        with pytest.raises(Exception) as exc:
            soft_delete_matter(matter=matter, user=admin)
        assert "clos" in str(exc.value).lower() or "archiv" in str(exc.value).lower()
        archived = archive_matter(matter=matter, user=admin)
        assert archived.is_archived is True
        assert archived.actions.filter(action="archived").exists()


@pytest.mark.django_db
def test_create_international_matter() -> None:
    """Un dossier peut être ouvert à l'échelle internationale."""
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    with cabinet_context(cabinet):
        client = create_client(
            cabinet=cabinet,
            user=user,
            client_type=ClientType.PERSON,
            first_name="Jean",
            last_name="Kabila",
        )
        matter = _open_matter(
            cabinet,
            user,
            client,
            "Coopération CPI",
            scale=MatterScale.INTERNATIONAL,
            jurisdiction="Cour pénale internationale",
        )
        assert matter.scale == MatterScale.INTERNATIONAL
        assert matter.jurisdiction == "Cour pénale internationale"


@pytest.mark.django_db
def test_create_matter_rejects_scale_jurisdiction_mismatch() -> None:
    """Une juridiction internationale ne peut pas être rattachée à l'échelle nationale."""
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    with cabinet_context(cabinet):
        client = create_client(
            cabinet=cabinet,
            user=user,
            client_type=ClientType.PERSON,
            first_name="Amina",
            last_name="Mwamba",
        )
        with pytest.raises(ValidationError) as exc:
            _open_matter(
                cabinet,
                user,
                client,
                "Dossier incohérent",
                scale=MatterScale.NATIONAL,
                jurisdiction="Cour pénale internationale",
            )
        assert "jurisdiction" in exc.value.message_dict


@pytest.mark.django_db
def test_matter_form_rejects_national_court_on_international_scale() -> None:
    """Le formulaire refuse un tribunal national pour un dossier international."""
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    with cabinet_context(cabinet):
        client = create_client(
            cabinet=cabinet,
            user=user,
            client_type=ClientType.PERSON,
            first_name="Paul",
            last_name="Ilunga",
        )
        form = MatterForm(
            data={
                "client": client.pk,
                "title": "Pourvoi cassation",
                "scale": MatterScale.INTERNATIONAL,
                "jurisdiction": "Cour de cassation",
                "status": MatterStatus.OPEN,
                "responsible_lawyer": user.pk,
            },
        )
        assert not form.is_valid()
        assert "jurisdiction" in form.errors


@pytest.mark.django_db
def test_matters_list_filter_by_scale(client) -> None:  # type: ignore[no-untyped-def]
    """La liste des dossiers peut être filtrée par échelle nationale ou internationale."""
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()
    with cabinet_context(cabinet):
        person = create_client(
            cabinet=cabinet,
            user=user,
            client_type=ClientType.PERSON,
            first_name="Léa",
            last_name="Tshisekedi",
        )
        _open_matter(
            cabinet,
            user,
            person,
            "Affaire TGI-Gombe unique",
            scale=MatterScale.NATIONAL,
            jurisdiction="Tribunal de grande instance de Kinshasa/Gombe",
        )
        _open_matter(
            cabinet,
            user,
            person,
            "Affaire CCJA unique",
            scale=MatterScale.INTERNATIONAL,
            jurisdiction="Cour commune de justice et d'arbitrage (OHADA)",
        )
        from apps.matters.models import Matter
        from apps.procurations.services import stamp_granted_procuration

        for matter in Matter.objects.filter(cabinet=cabinet):
            stamp_granted_procuration(matter=matter, actor=user)
    resp = client.get(reverse("matters:list"), {"scale": "international"})
    assert resp.status_code == 200
    assert b"Affaire CCJA unique" in resp.content
    assert b"Affaire TGI-Gombe unique" not in resp.content


@pytest.mark.django_db
def test_cabinet_cannot_create_matter(client) -> None:  # type: ignore[no-untyped-def]
    """Le cabinet ne peut pas ouvrir un dossier : réservé au ministère."""
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()
    assert client.get(reverse("matters:create")).status_code == 403
    with cabinet_context(cabinet):
        with pytest.raises(PermissionDenied):
            create_matter(
                user=user,
                title="Dossier illicite",
            )


@pytest.mark.django_db
def test_cabinet_cannot_update_or_delete_matter(client) -> None:  # type: ignore[no-untyped-def]
    """Le cabinet ne peut ni modifier ni supprimer un dossier."""
    user = UserFactory()
    admin = UserFactory(is_platform_admin=True)
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    matter = _open_matter(cabinet, user, None, "Dossier protégé")
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()
    assert client.get(reverse("matters:update", args=[matter.pk])).status_code == 403
    assert client.post(reverse("matters:delete", args=[matter.pk])).status_code == 403
    with pytest.raises(PermissionDenied):
        update_matter(matter=matter, user=user, title="Hack")
    with pytest.raises(PermissionDenied):
        soft_delete_matter(matter=matter, user=user)
    # Le ministère conserve les droits
    update_matter(matter=matter, user=admin, title="Titre ministère")
    matter.refresh_from_db()
    assert matter.title == "Titre ministère"


@pytest.mark.django_db
def test_cabinet_only_sees_matters_with_procuration(client) -> None:  # type: ignore[no-untyped-def]
    """Le cabinet ne voit que les dossiers pour lesquels une procuration est valide."""
    user = UserFactory()
    admin = UserFactory(is_platform_admin=True)
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()
    with cabinet_context(cabinet):
        person = create_client(
            cabinet=cabinet,
            user=user,
            client_type=ClientType.PERSON,
            last_name="Mwamba",
        )
        hidden = create_matter(
            user=admin,
            title="Sans procuration",
        )
        visible = create_matter(
            user=admin,
            title="Avec procuration",
        )
        from apps.procurations.services import stamp_granted_procuration

        stamp_granted_procuration(matter=visible, cabinet=cabinet, actor=admin)

    listing = client.get(reverse("matters:list"))
    html = listing.content.decode()
    assert listing.status_code == 200
    assert "Avec procuration" in html
    assert "Sans procuration" not in html
    assert client.get(reverse("matters:detail", args=[visible.pk])).status_code == 200
    assert client.get(reverse("matters:detail", args=[hidden.pk])).status_code == 404
