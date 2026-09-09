"""Affectation d'un ou plusieurs avocats à un dossier par le cabinet."""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.matters.models import MatterLawyer
from apps.matters.services import assign_matter_lawyers, create_matter
from apps.procurations.services import stamp_granted_procuration
from apps.tenants.roles import Role
from tests.factories import CabinetFactory, MembershipFactory, UserFactory


def _matter_with_cabinet(cabinet, *, with_procuration: bool = True):  # type: ignore[no-untyped-def]
    admin = UserFactory(is_platform_admin=True)
    matter = create_matter(user=admin, title="Affaire avocats")
    if with_procuration:
        stamp_granted_procuration(matter=matter, cabinet=cabinet, actor=admin)
        matter.refresh_from_db()
    return matter, admin


@pytest.mark.django_db
def test_cabinet_can_assign_multiple_lawyers() -> None:
    cabinet = CabinetFactory()
    caiman = UserFactory(first_name="Caïman", last_name="Kongo")
    lawyer_a = UserFactory(first_name="Ada", last_name="Mbala")
    lawyer_b = UserFactory(first_name="Bob", last_name="Lukusa")
    MembershipFactory(user=caiman, cabinet=cabinet, role=Role.CAIMAN)
    MembershipFactory(user=lawyer_a, cabinet=cabinet, role=Role.LAWYER)
    MembershipFactory(user=lawyer_b, cabinet=cabinet, role=Role.LAWYER)
    matter, _ = _matter_with_cabinet(cabinet)

    assign_matter_lawyers(
        matter=matter,
        user=caiman,
        lawyers=[lawyer_a, lawyer_b],
        lead=lawyer_b,
    )
    matter.refresh_from_db()

    assert matter.responsible_lawyer_id == lawyer_b.pk
    assigned = list(
        MatterLawyer.objects.filter(matter=matter).order_by("lawyer__last_name")
    )
    assert len(assigned) == 2
    assert {item.lawyer_id for item in assigned} == {lawyer_a.pk, lawyer_b.pk}
    assert MatterLawyer.objects.get(matter=matter, lawyer=lawyer_b).is_lead is True
    assert MatterLawyer.objects.get(matter=matter, lawyer=lawyer_a).is_lead is False


@pytest.mark.django_db
def test_assign_lawyers_requires_valid_procuration() -> None:
    cabinet = CabinetFactory()
    user = UserFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.CAIMAN)
    matter, _ = _matter_with_cabinet(cabinet, with_procuration=False)
    matter.cabinet = cabinet
    matter.save(update_fields=["cabinet"])

    with pytest.raises(ValidationError):
        assign_matter_lawyers(matter=matter, user=user, lawyers=[user])


@pytest.mark.django_db
def test_platform_admin_cannot_assign_lawyers() -> None:
    cabinet = CabinetFactory()
    lawyer = UserFactory()
    MembershipFactory(user=lawyer, cabinet=cabinet, role=Role.LAWYER)
    matter, admin = _matter_with_cabinet(cabinet)

    with pytest.raises(PermissionDenied):
        assign_matter_lawyers(matter=matter, user=admin, lawyers=[lawyer])


@pytest.mark.django_db
def test_assign_lawyers_http(client) -> None:  # type: ignore[no-untyped-def]
    cabinet = CabinetFactory()
    user = UserFactory()
    lawyer_a = UserFactory()
    lawyer_b = UserFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.CAIMAN)
    MembershipFactory(user=lawyer_a, cabinet=cabinet, role=Role.LAWYER)
    MembershipFactory(user=lawyer_b, cabinet=cabinet, role=Role.LAWYER)
    matter, _ = _matter_with_cabinet(cabinet)

    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()

    url = reverse("matters:assign_lawyers", kwargs={"pk": matter.pk})
    response = client.get(url)
    assert response.status_code == 200

    response = client.post(
        url,
        {"lawyers": [str(lawyer_a.pk), str(lawyer_b.pk)], "lead": str(lawyer_a.pk)},
    )
    assert response.status_code == 302
    matter.refresh_from_db()
    assert matter.responsible_lawyer_id == lawyer_a.pk
    assert MatterLawyer.objects.filter(matter=matter).count() == 2
