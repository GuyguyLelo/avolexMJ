"""Tests du module Procurations ministérielles."""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.calendar_app.models import EventType
from apps.calendar_app.services import create_event
from apps.clients.models import ClientType
from apps.clients.services import create_client
from apps.matters.models import MatterStatus
from apps.matters.services import create_matter, update_matter
from apps.procurations.models import Procuration, ProcurationStatus
from apps.procurations.services import (
    approve_by_conseiller,
    create_procuration,
    get_valid_procuration,
    grant_procuration,
    matter_has_valid_procuration,
    revoke_procuration,
)
from apps.tenants.context import cabinet_context
from apps.tenants.roles import Role
from tests.factories import (
    CabinetFactory,
    MatterFactory,
    MembershipFactory,
    UserFactory,
)


def _grant_fully(procuration: Procuration, **_ignored: object) -> Procuration:
    """Complète le circuit Conseiller → Dircaba (rôles distincts)."""
    from apps.accounts.models import MinistryRole

    conseiller = UserFactory(
        is_platform_admin=True,
        ministry_role=MinistryRole.CONSEILLER,
    )
    dircaba = UserFactory(
        is_platform_admin=True,
        ministry_role=MinistryRole.DIRCABA,
    )
    approve_by_conseiller(procuration=procuration, actor=conseiller)
    return grant_procuration(procuration=procuration, actor=dircaba)


@pytest.mark.django_db
def test_matter_activity_blocked_without_procuration() -> None:
    """Sans procuration accordée, aucun acte n'est possible sur le dossier."""
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    with cabinet_context(cabinet):
        matter = MatterFactory(
            cabinet=cabinet,
            with_procuration=False,
            responsible_lawyer=user,
            title="Dossier sans mandat",
        )
        assert matter_has_valid_procuration(matter) is False
        with pytest.raises(ValidationError, match="procuration"):
            create_event(
                cabinet=cabinet,
                user=user,
                title="Audience",
                starts_at=timezone.now(),
                event_type=EventType.HEARING,
                matter=matter,
            )
        with pytest.raises(PermissionDenied):
            update_matter(matter=matter, user=user, status=MatterStatus.IN_PROGRESS)


@pytest.mark.django_db
def test_grant_unlocks_matter_activity() -> None:
    """Après octroi ministériel, le cabinet peut agir sur le dossier."""
    owner = UserFactory()
    admin = UserFactory(is_platform_admin=True)
    cabinet = CabinetFactory()
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    with cabinet_context(cabinet):
        client = create_client(
            cabinet=cabinet,
            user=owner,
            client_type=ClientType.PERSON,
            last_name="Ilunga",
        )
        matter = create_matter(
            user=admin,
            title="Affaire civile",
        )
        procuration = create_procuration(
            cabinet=cabinet,
            user=admin,
            matter=matter,
            purpose="Représentation en justice",
            ministry_reference="MJ/GS/2026/014",
        )
        assert procuration.status == ProcurationStatus.REQUESTED
        procuration = _grant_fully(procuration)
        assert procuration.status == ProcurationStatus.GRANTED
        assert procuration.is_currently_valid is True
        matter.refresh_from_db()
        assert matter.cabinet_id == cabinet.pk
        event = create_event(
            cabinet=cabinet,
            user=owner,
            title="Audience TGI Gombe",
            starts_at=timezone.now(),
            event_type=EventType.HEARING,
            matter=matter,
        )
        assert event.matter_id == matter.pk


@pytest.mark.django_db
def test_cabinet_cannot_grant_procuration() -> None:
    """Seul le ministère peut délivrer une procuration."""
    owner = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    with cabinet_context(cabinet):
        matter = MatterFactory(cabinet=cabinet, with_procuration=False, responsible_lawyer=owner)
        with pytest.raises(PermissionDenied):
            create_procuration(
                cabinet=cabinet,
                user=owner,
                matter=matter,
                purpose="Actes de procédure",
            )


@pytest.mark.django_db
def test_matter_factory_has_valid_procuration() -> None:
    """Les dossiers de test reçoivent une procuration accordée par défaut."""
    matter = MatterFactory()
    with cabinet_context(matter.cabinet):
        assert matter_has_valid_procuration(matter) is True


@pytest.mark.django_db
def test_revoke_blocks_matter_activity() -> None:
    """La révocation ministérielle rebloque le dossier."""
    owner = UserFactory()
    admin = UserFactory(is_platform_admin=True)
    cabinet = CabinetFactory()
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    with cabinet_context(cabinet):
        matter = MatterFactory(cabinet=cabinet, with_procuration=False, responsible_lawyer=owner)
        procuration = create_procuration(
            cabinet=cabinet,
            user=admin,
            matter=matter,
            purpose="Représentation",
        )
        procuration = _grant_fully(procuration)
        assert matter_has_valid_procuration(matter) is True
        revoke_procuration(procuration=procuration, actor=admin, reason="Mandat retiré")
        assert matter_has_valid_procuration(matter) is False


@pytest.mark.django_db
def test_procuration_list_http(client) -> None:  # type: ignore[no-untyped-def]
    """La liste des procurations est accessible au cabinet (lecture seule)."""
    user = UserFactory()
    admin = UserFactory(is_platform_admin=True)
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.LAWYER)
    matter = MatterFactory(cabinet=cabinet, with_procuration=False, responsible_lawyer=user)
    with cabinet_context(cabinet):
        create_procuration(
            cabinet=cabinet,
            user=admin,
            matter=matter,
            purpose="Mandat de représentation",
        )
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()
    resp = client.get(reverse("procurations:list"))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Mandat de représentation" in html
    assert "Délivrer une procuration" not in html
    assert "Nouvelle procuration" not in html
    assert client.get(reverse("procurations:create")).status_code == 403


@pytest.mark.django_db
def test_cabinet_cannot_create_procuration_http(client) -> None:  # type: ignore[no-untyped-def]
    """Le cabinet ne peut pas délivrer une procuration."""
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    matter = MatterFactory(cabinet=cabinet, with_procuration=False, responsible_lawyer=user)
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()
    assert client.get(reverse("procurations:create")).status_code == 403
    create_resp = client.post(
        reverse("procurations:create"),
        {
            "cabinet": str(cabinet.pk),
            "matter": str(matter.pk),
            "purpose": "Représentation en justice",
        },
    )
    assert create_resp.status_code == 403
    with cabinet_context(cabinet):
        assert not Procuration.objects.filter(purpose="Représentation en justice").exists()


@pytest.mark.django_db
def test_ministry_issues_procuration_http(client) -> None:  # type: ignore[no-untyped-def]
    """Synthia crée, Conseiller valide, Dircaba vise, puis Synthia peut générer le Word."""
    from apps.accounts.models import MinistryRole

    owner = UserFactory()
    synthia = UserFactory(is_platform_admin=True, ministry_role=MinistryRole.ADMIN)
    conseiller = UserFactory(is_platform_admin=True, ministry_role=MinistryRole.CONSEILLER)
    dircaba = UserFactory(is_platform_admin=True, ministry_role=MinistryRole.DIRCABA)
    cabinet = CabinetFactory()
    other = CabinetFactory()
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    matter = MatterFactory(cabinet=cabinet, with_procuration=False, responsible_lawyer=owner)
    client.force_login(synthia)
    session = client.session
    session["cabinet_id"] = str(other.pk)
    session.save()

    create_page = client.get(reverse("procurations:create"))
    assert create_page.status_code == 200
    create_html = create_page.content.decode()
    assert "Délivrer une procuration" in create_html
    assert "Cabinet avocat" in create_html

    create_resp = client.post(
        reverse("procurations:create"),
        {
            "cabinet": str(cabinet.pk),
            "matter": str(matter.pk),
            "notes": "Représentation en justice",
        },
    )
    assert create_resp.status_code == 302, create_resp.content.decode()[:500]
    with cabinet_context(cabinet):
        procuration = Procuration.objects.get(matter=matter)
        assert procuration.status == ProcurationStatus.REQUESTED
        assert procuration.matter_id == matter.pk
        pk = procuration.pk

    # Synthia ne valide pas elle-même.
    detail = client.get(reverse("procurations:detail", args=[pk]))
    assert detail.status_code == 200
    assert "Valider (Conseiller)" not in detail.content.decode()
    assert "Générer Word" not in detail.content.decode()
    assert matter_has_valid_procuration(matter) is False

    client.force_login(conseiller)
    detail = client.get(reverse("procurations:detail", args=[pk]))
    assert "Valider (Conseiller)" in detail.content.decode()
    approve = client.post(reverse("procurations:approve_conseiller", args=[pk]))
    assert approve.status_code == 302

    client.force_login(dircaba)
    grant = client.post(
        reverse("procurations:grant", args=[pk]),
        {"ministry_reference": "MJ/GS/2026/014"},
    )
    assert grant.status_code == 302
    with cabinet_context(cabinet):
        procuration = Procuration.objects.get(pk=pk)
        assert procuration.status == ProcurationStatus.GRANTED
        assert procuration.conseiller_by_id == conseiller.pk
        assert procuration.granted_by_id == dircaba.pk
    assert matter_has_valid_procuration(matter) is True

    client.force_login(synthia)
    detail = client.get(reverse("procurations:detail", args=[pk]))
    html = detail.content.decode()
    assert "Corriger l'acte" in html
    assert "Générer Word" in html
    word = client.get(reverse("procurations:word", args=[pk]))
    assert word.status_code == 200
    assert word.content[:2] == b"PK"


@pytest.mark.django_db
def test_ministry_lists_issued_procurations(client) -> None:  # type: ignore[no-untyped-def]
    """Le ministère voit les procurations de tous les cabinets."""
    owner = UserFactory()
    admin = UserFactory(is_platform_admin=True)
    cabinet = CabinetFactory()
    other = CabinetFactory()
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    matter = MatterFactory(cabinet=cabinet, with_procuration=False, responsible_lawyer=owner)
    with cabinet_context(cabinet):
        proc = create_procuration(
            cabinet=cabinet,
            user=admin,
            matter=matter,
            purpose="Mandat CPI",
            ministry_reference="MJ/GS/2026/001",
        )
        _grant_fully(proc)

    client.force_login(admin)
    session = client.session
    session["cabinet_id"] = str(other.pk)
    session.save()

    listing = client.get(reverse("procurations:list"))
    assert listing.status_code == 200
    html = listing.content.decode()
    assert "Mandat CPI" in html
    assert "Délivrer une procuration" in html
    assert cabinet.name in html
    assert client.get(reverse("procurations:create")).status_code == 200
    with cabinet_context(cabinet):
        assert matter_has_valid_procuration(matter) is True


@pytest.mark.django_db
def test_conseiller_then_dircaba_roles() -> None:
    """Synthia crée ; Conseiller valide ; Dircaba vise ; Synthia seule génère le Word."""
    from apps.accounts.models import MinistryRole

    owner = UserFactory()
    synthia = UserFactory(is_platform_admin=True, ministry_role=MinistryRole.ADMIN)
    conseiller = UserFactory(
        is_platform_admin=True,
        ministry_role=MinistryRole.CONSEILLER,
        first_name="Paul",
        last_name="Conseiller",
    )
    dircaba = UserFactory(
        is_platform_admin=True,
        ministry_role=MinistryRole.DIRCABA,
        first_name="Jeanne",
        last_name="Dircaba",
    )
    cabinet = CabinetFactory()
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    with cabinet_context(cabinet):
        matter = MatterFactory(cabinet=cabinet, with_procuration=False, responsible_lawyer=owner)
        with pytest.raises(PermissionDenied):
            create_procuration(
                cabinet=cabinet,
                user=conseiller,
                matter=matter,
                purpose="Double validation",
            )
        procuration = create_procuration(
            cabinet=cabinet,
            user=synthia,
            matter=matter,
            purpose="Double validation",
        )
        with pytest.raises(PermissionDenied):
            approve_by_conseiller(procuration=procuration, actor=synthia)
        with pytest.raises(ValidationError):
            grant_procuration(procuration=procuration, actor=dircaba)
        with pytest.raises(PermissionDenied):
            approve_by_conseiller(procuration=procuration, actor=dircaba)
        approve_by_conseiller(procuration=procuration, actor=conseiller)
        procuration.refresh_from_db()
        assert procuration.status == ProcurationStatus.APPROVED_CONSEILLER
        with pytest.raises(PermissionDenied):
            grant_procuration(procuration=procuration, actor=conseiller)
        with pytest.raises(PermissionDenied):
            grant_procuration(procuration=procuration, actor=synthia)
        grant_procuration(procuration=procuration, actor=dircaba)
        procuration.refresh_from_db()
        assert procuration.status == ProcurationStatus.GRANTED
        assert procuration.conseiller_by_id == conseiller.pk
        assert procuration.granted_by_id == dircaba.pk


@pytest.mark.django_db
@pytest.mark.parametrize(
    "flags",
    [
        {"is_super_admin": True, "is_platform_admin": True},
        {"is_super_admin": False, "is_platform_admin": True, "first_name": "Synthia"},
    ],
)
def test_superadmin_and_supervisor_see_procurations_without_cabinet(
    client,  # type: ignore[no-untyped-def]
    flags: dict[str, object],
) -> None:
    """SuperAdmin et Synthia (superviseur) voient liste + fiche sans cabinet en session."""
    owner = UserFactory()
    supervisor = UserFactory(**flags)
    cabinet = CabinetFactory(name="Cabinet Synthia Test")
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    matter = MatterFactory(cabinet=cabinet, with_procuration=False, responsible_lawyer=owner)
    with cabinet_context(cabinet):
        procuration = create_procuration(
            cabinet=cabinet,
            user=supervisor,
            matter=matter,
            purpose="Mandat supervision nationale",
        )
        pk = procuration.pk

    client.force_login(supervisor)
    # Pas de cabinet_id en session (compte ministère détaché).
    assert "cabinet_id" not in client.session

    listing = client.get(reverse("procurations:list"))
    assert listing.status_code == 200
    html = listing.content.decode()
    assert "Mandat supervision nationale" in html
    assert "Cabinet Synthia Test" in html

    detail = client.get(reverse("procurations:detail", args=[pk]))
    assert detail.status_code == 200
    assert "Mandat supervision nationale" in detail.content.decode()


@pytest.mark.django_db
def test_new_procuration_starts_with_cabinet(client) -> None:  # type: ignore[no-untyped-def]
    """La création commence par le cabinet : les dossiers n'apparaissent qu'après sélection."""
    owner = UserFactory()
    admin = UserFactory(is_platform_admin=True)
    cabinet = CabinetFactory(name="ILEO Law Firm")
    other = CabinetFactory(name="Cabinet concurrent")
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    matter = MatterFactory(
        cabinet=cabinet,
        with_procuration=False,
        responsible_lawyer=owner,
        title="Dossier ILEO",
    )
    MatterFactory(cabinet=other, with_procuration=False, title="Dossier concurrent")

    client.force_login(admin)
    session = client.session
    session["cabinet_id"] = str(other.pk)
    session.save()

    blank = client.get(reverse("procurations:create"))
    html = blank.content.decode()
    assert blank.status_code == 200
    assert "Cabinet avocat" in html
    assert "Sélectionner un cabinet" in html
    assert "Dossier ILEO" not in html
    assert "Dossier concurrent" not in html

    filtered = client.get(reverse("procurations:create"), {"cabinet": str(cabinet.pk)})
    html = filtered.content.decode()
    assert "Dossier ILEO" in html
    assert "Dossier concurrent" not in html

    created = client.post(
        reverse("procurations:create"),
        {
            "cabinet": str(cabinet.pk),
            "matter": str(matter.pk),
            "notes": "Mandat ministériel",
        },
    )
    assert created.status_code == 302, created.content.decode()[:500]
    with cabinet_context(cabinet):
        procuration = Procuration.objects.get(matter=matter)
        assert procuration.status == ProcurationStatus.REQUESTED
        assert "Mandat ministériel" in (procuration.notes or "")


@pytest.mark.django_db
def test_matter_detail_shows_procuration(client) -> None:  # type: ignore[no-untyped-def]
    """La fiche dossier renseigne la procuration ministérielle."""
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    matter = MatterFactory(cabinet=cabinet, responsible_lawyer=user, title="Affaire Gombe")
    with cabinet_context(cabinet):
        procuration = get_valid_procuration(matter)
        assert procuration is not None
        reference = procuration.reference
        purpose = procuration.purpose

    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()
    resp = client.get(reverse("matters:detail", args=[matter.pk]))
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "Procuration" in html
    assert reference in html
    assert purpose in html
    assert "Réf. ministérielle" in html or "Référence ministérielle" in html
    assert "Voir" in html
    assert "Demander une procuration" not in html


@pytest.mark.django_db
def test_procuration_instrument_can_be_displayed(client) -> None:  # type: ignore[no-untyped-def]
    """L'acte joint s'affiche en aperçu et se télécharge."""
    user = UserFactory()
    admin = UserFactory(is_platform_admin=True)
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    matter = MatterFactory(cabinet=cabinet, with_procuration=False, responsible_lawyer=user)
    pdf = SimpleUploadedFile(
        "acte-ministere.pdf",
        b"%PDF-1.4 fake",
        content_type="application/pdf",
    )
    with cabinet_context(cabinet):
        procuration = create_procuration(
            cabinet=cabinet,
            user=admin,
            matter=matter,
            purpose="Mandat de représentation",
            instrument=pdf,
        )
        pk = procuration.pk
        assert procuration.instrument_can_preview is True

    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()

    detail = client.get(reverse("procurations:detail", args=[pk]))
    assert detail.status_code == 200
    html = detail.content.decode()
    assert "Afficher" in html
    assert reverse("procurations:preview", args=[pk]) in html
    assert "Acte joint" not in html

    preview = client.get(reverse("procurations:preview", args=[pk]))
    assert preview.status_code == 200
    disposition = (preview.get("Content-Disposition") or "").lower()
    assert "inline" in disposition
    assert preview["Content-Type"].startswith("application/pdf")

    download = client.get(reverse("procurations:download", args=[pk]))
    assert download.status_code == 200
    assert "attachment" in (download.get("Content-Disposition") or "").lower()


@pytest.mark.django_db
def test_conseiller_can_view_live_pdf(client) -> None:  # type: ignore[no-untyped-def]
    """Conseiller affiche le PDF pour valider, sans Word ni corrections."""
    from apps.accounts.models import MinistryRole

    owner = UserFactory()
    synthia = UserFactory(is_platform_admin=True, ministry_role=MinistryRole.ADMIN)
    conseiller = UserFactory(
        is_platform_admin=True,
        ministry_role=MinistryRole.CONSEILLER,
    )
    cabinet = CabinetFactory()
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    matter = MatterFactory(cabinet=cabinet, with_procuration=False, responsible_lawyer=owner)
    with cabinet_context(cabinet):
        procuration = create_procuration(
            cabinet=cabinet,
            user=synthia,
            matter=matter,
            purpose="Mandat de représentation",
            ministry_reference="MJ/GS/2026/201",
        )
        pk = procuration.pk
        assert not procuration.instrument

    client.force_login(conseiller)
    detail = client.get(reverse("procurations:detail", args=[pk]))
    assert detail.status_code == 200
    html = detail.content.decode()
    assert "Afficher PDF" in html
    assert "Télécharger PDF" in html
    assert "Générer Word" not in html
    assert "Corriger l'acte" not in html
    assert reverse("procurations:preview", args=[pk]) in html

    preview = client.get(reverse("procurations:preview", args=[pk]))
    assert preview.status_code == 200
    assert preview["Content-Type"].startswith("application/pdf")
    assert "inline" in (preview.get("Content-Disposition") or "").lower()
    assert preview.content.startswith(b"%PDF")

    pdf = client.get(reverse("procurations:pdf", args=[pk]))
    assert pdf.status_code == 200
    assert "attachment" in (pdf.get("Content-Disposition") or "").lower()
    assert pdf.content.startswith(b"%PDF")

    word = client.get(reverse("procurations:word", args=[pk]))
    assert word.status_code == 403


@pytest.mark.django_db
def test_ministry_generates_procuration_pdf(client) -> None:  # type: ignore[no-untyped-def]
    """Le ministère génère l'acte PDF et le joint à la procuration."""
    owner = UserFactory()
    admin = UserFactory(is_platform_admin=True)
    cabinet = CabinetFactory()
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    matter = MatterFactory(cabinet=cabinet, with_procuration=False, responsible_lawyer=owner)
    with cabinet_context(cabinet):
        procuration = create_procuration(
            cabinet=cabinet,
            user=admin,
            matter=matter,
            purpose="Représentation en justice",
            ministry_reference="MJ/GS/2026/200",
        )
        procuration = _grant_fully(procuration)
        pk = procuration.pk
        assert not procuration.instrument

    client.force_login(admin)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()

    detail = client.get(reverse("procurations:detail", args=[pk]))
    assert detail.status_code == 200
    html = detail.content.decode()
    assert "Corriger l'acte" in html
    assert reverse("procurations:editor", args=[pk]) in html
    assert reverse("procurations:generate", args=[pk]) in html
    assert "Générer Word" in html

    editor = client.get(reverse("procurations:editor", args=[pk]))
    assert editor.status_code == 200
    assert b"contenteditable" in editor.content
    assert b"PROCURATION" in editor.content

    save = client.post(
        reverse("procurations:editor", args=[pk]),
        {
            "action": "save",
            "draft_html": "<p class='title'><strong>// PROCURATION //</strong></p><p>Texte mis en forme.</p>",
        },
    )
    assert save.status_code == 302
    with cabinet_context(cabinet):
        procuration = Procuration.objects.get(pk=pk)
        assert "PROCURATION" in procuration.draft_html
        assert "Texte mis en forme" in procuration.draft_html

    generate = client.post(reverse("procurations:generate", args=[pk]))
    assert generate.status_code == 302

    with cabinet_context(cabinet):
        procuration = Procuration.objects.get(pk=pk)
        assert procuration.instrument
        assert procuration.instrument_filename.endswith(".pdf")
        data = procuration.instrument.read()
        assert data.startswith(b"%PDF")

    after = client.get(reverse("procurations:detail", args=[pk]))
    assert after.status_code == 200
    after_html = after.content.decode()
    assert "Publier PDF" in after_html
    assert reverse("procurations:preview", args=[pk]) in after_html


@pytest.mark.django_db
def test_cabinet_cannot_generate_procuration_pdf(client) -> None:  # type: ignore[no-untyped-def]
    """Le cabinet ne peut pas générer l'acte ministériel."""
    owner = UserFactory()
    admin = UserFactory(is_platform_admin=True)
    cabinet = CabinetFactory()
    MembershipFactory(user=owner, cabinet=cabinet, role=Role.OWNER)
    matter = MatterFactory(cabinet=cabinet, with_procuration=False, responsible_lawyer=owner)
    with cabinet_context(cabinet):
        procuration = create_procuration(
            cabinet=cabinet,
            user=admin,
            matter=matter,
            purpose="Mandat de représentation",
        )
        pk = procuration.pk

    client.force_login(owner)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()

    detail = client.get(reverse("procurations:detail", args=[pk]))
    assert detail.status_code == 200
    assert "Éditer l'acte" not in detail.content.decode()

    generate = client.post(reverse("procurations:generate", args=[pk]))
    assert generate.status_code == 403
    editor = client.get(reverse("procurations:editor", args=[pk]))
    assert editor.status_code in (302, 403)
    with cabinet_context(cabinet):
        procuration = Procuration.objects.get(pk=pk)
        assert not procuration.instrument
