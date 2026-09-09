"""Tests module Audiences."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.calendar_app.models import EventType, HearingStatus
from apps.calendar_app.services import (
    create_event,
    hearings_queryset,
    save_hearing_report,
    update_hearing_status,
)
from apps.clients.models import ClientType
from apps.clients.services import create_client
from apps.matters.services import create_matter
from apps.tenants.context import cabinet_context
from apps.tenants.roles import Role
from tests.factories import CabinetFactory, MembershipFactory, UserFactory


def _pdf_report(name: str = "rapport-audience.pdf") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, b"%PDF-1.4 fake", content_type="application/pdf")


@pytest.mark.django_db
def test_hearing_create_and_list(client) -> None:  # type: ignore[no-untyped-def]
    """Création audience + liste dédiée."""
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.LAWYER)
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()

    with cabinet_context(cabinet):
        cl = create_client(
            cabinet=cabinet,
            user=user,
            client_type=ClientType.PERSON,
            last_name="Durand",
        )
        admin = UserFactory(is_platform_admin=True)
        matter = create_matter(
            user=admin,
            title="Litige commercial",
        )
        from apps.procurations.services import stamp_granted_procuration

        stamp_granted_procuration(matter=matter, cabinet=cabinet, actor=admin)
        hearing = create_event(
            cabinet=cabinet,
            user=user,
            title="Audience de fond",
            starts_at=timezone.now() + timedelta(days=3),
            event_type=EventType.HEARING,
            matter=matter,
            court="Tribunal de grande instance de Kinshasa/Gombe",
            chamber="1re ch. civ.",
        )
        assert hearing.hearing_status == HearingStatus.SCHEDULED

        listed = hearings_queryset(cabinet=cabinet, upcoming_only=True)
        assert listed.filter(pk=hearing.pk).exists()

    resp = client.get(reverse("hearings:list"))
    assert resp.status_code == 200
    assert b"Audience de fond" in resp.content
    assert b"Tribunal de grande instance de Kinshasa/Gombe" in resp.content


@pytest.mark.django_db
def test_hearing_status_update() -> None:
    """Marquer une audience comme tenue."""
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    with cabinet_context(cabinet):
        hearing = create_event(
            cabinet=cabinet,
            user=user,
            title="Audience référé",
            starts_at=timezone.now() + timedelta(days=1),
            event_type=EventType.HEARING,
            court="Tribunal de paix de Kinshasa/Lemba",
        )
        updated = update_hearing_status(
            event=hearing,
            user=user,
            hearing_status=HearingStatus.HELD,
            hearing_report="Renvoi au 15/09.",
        )
        assert updated.hearing_status == HearingStatus.HELD
        assert updated.is_done is True
        assert "Renvoi" in updated.hearing_report


@pytest.mark.django_db
def test_hearing_report_can_be_added(client) -> None:  # type: ignore[no-untyped-def]
    """Plusieurs fichiers Word/PDF peuvent être joints à une audience."""
    from apps.calendar_app.models import HearingAttachment

    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.LAWYER)
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()

    with cabinet_context(cabinet):
        hearing = create_event(
            cabinet=cabinet,
            user=user,
            title="Audience de fond",
            starts_at=timezone.now() + timedelta(days=2),
            event_type=EventType.HEARING,
        )

    detail = client.get(reverse("calendar:event_detail", args=[hearing.pk]))
    assert detail.status_code == 200
    html = detail.content.decode()
    assert "Joindre des fichiers" in html
    assert "Joindre des fichiers Word ou PDF" in html

    pdf = _pdf_report()
    pdf2 = _pdf_report("piece-2.pdf")
    resp = client.post(
        reverse("hearings:report", args=[hearing.pk]),
        {"report_files": [pdf, pdf2], "mark_held": "1"},
    )
    assert resp.status_code == 302
    hearing.refresh_from_db()
    attachments = list(HearingAttachment.objects.filter(event=hearing).order_by("created_at"))
    assert len(attachments) == 2
    assert attachments[0].original_filename == "rapport-audience.pdf"
    assert attachments[1].original_filename == "piece-2.pdf"
    assert hearing.has_hearing_report is True
    assert hearing.hearing_status == HearingStatus.HELD
    assert hearing.is_done is True

    preview = client.get(
        reverse(
            "hearings:attachment_preview",
            args=[hearing.pk, attachments[0].pk],
        )
    )
    assert preview.status_code == 200
    assert preview["Content-Type"].startswith("application/pdf")
    assert "inline" in (preview.get("Content-Disposition") or "").lower()

    download = client.get(
        reverse(
            "hearings:attachment_download",
            args=[hearing.pk, attachments[0].pk],
        )
    )
    assert download.status_code == 200
    assert "attachment" in (download.get("Content-Disposition") or "").lower()

    # Compatibilité des anciennes URLs
    assert client.get(reverse("hearings:report_download", args=[hearing.pk])).status_code == 200
    assert client.get(reverse("hearings:report_preview", args=[hearing.pk])).status_code == 200


@pytest.mark.django_db
def test_hearing_report_rejects_non_word_pdf(client) -> None:  # type: ignore[no-untyped-def]
    """Les fichiers autres que Word/PDF sont refusés."""
    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.LAWYER)
    client.force_login(user)
    session = client.session
    session["cabinet_id"] = str(cabinet.pk)
    session.save()

    with cabinet_context(cabinet):
        hearing = create_event(
            cabinet=cabinet,
            user=user,
            title="Audience de fond",
            starts_at=timezone.now() + timedelta(days=2),
            event_type=EventType.HEARING,
        )

    bad = SimpleUploadedFile("malware.exe", b"MZ", content_type="application/x-msdownload")
    resp = client.post(
        reverse("hearings:report", args=[hearing.pk]),
        {"report_files": [bad]},
    )
    assert resp.status_code == 302
    hearing.refresh_from_db()
    assert hearing.attachments.count() == 0
    assert not hearing.hearing_report_file


@pytest.mark.django_db
def test_hearing_report_accepts_docx() -> None:
    """Un fichier Word .docx est accepté et se télécharge sans aperçu."""
    from apps.calendar_app.models import HearingAttachment

    user = UserFactory()
    cabinet = CabinetFactory()
    MembershipFactory(user=user, cabinet=cabinet, role=Role.OWNER)
    with cabinet_context(cabinet):
        hearing = create_event(
            cabinet=cabinet,
            user=user,
            title="Audience de fond",
            starts_at=timezone.now() + timedelta(days=2),
            event_type=EventType.HEARING,
        )
        uploaded = SimpleUploadedFile(
            "rapport.docx",
            b"PK\x03\x04 fake-docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        save_hearing_report(event=hearing, user=user, uploaded=uploaded)
        hearing.refresh_from_db()
        attachment = HearingAttachment.objects.get(event=hearing)
        assert attachment.original_filename == "rapport.docx"
        assert attachment.can_preview is False
        assert hearing.has_hearing_report is True
