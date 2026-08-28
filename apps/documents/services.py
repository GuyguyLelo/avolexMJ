"""Services GED : upload, versioning, contrôles d'accès."""

from __future__ import annotations

import hashlib
import logging
import mimetypes
from typing import TYPE_CHECKING, BinaryIO

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from apps.documents.models import Document, DocumentVersion
from apps.tenants.roles import PERM_ADD, PERM_CHANGE, PERM_DELETE, PERM_VIEW
from apps.tenants.services import require_cabinet_perm

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.matters.models import Matter
    from apps.tenants.models import Cabinet

logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
        "text/plain",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.oasis.opendocument.text",
        "application/zip",
    }
)

PREVIEWABLE_MIME_PREFIXES = ("image/",)
PREVIEWABLE_MIME_TYPES = frozenset({"application/pdf", "text/plain"})


def get_max_upload_bytes() -> int:
    """Taille max d'upload (octets)."""
    return int(getattr(settings, "DOCUMENTS_MAX_UPLOAD_BYTES", 20 * 1024 * 1024))


def get_allowed_mime_types() -> frozenset[str]:
    """Types MIME autorisés."""
    configured = getattr(settings, "DOCUMENTS_ALLOWED_MIME_TYPES", None)
    if configured:
        return frozenset(configured)
    return DEFAULT_ALLOWED_MIME_TYPES


def normalize_tags(tags: list[str] | None) -> list[str]:
    """Normalise et déduplique les tags."""
    if not tags:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for raw in tags:
        tag = raw.strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        result.append(tag[:64])
    return result


def compute_checksum(file_obj: BinaryIO) -> tuple[str, int]:
    """Calcule SHA-256 et taille ; remet le curseur à 0."""
    digest = hashlib.sha256()
    size = 0
    file_obj.seek(0)
    while True:
        chunk = file_obj.read(1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
        size += len(chunk)
    file_obj.seek(0)
    return digest.hexdigest(), size


def detect_mime_type(filename: str, content_type: str | None = None) -> str:
    """Déduit un type MIME fiable à partir du nom / Content-Type client."""
    guessed, _ = mimetypes.guess_type(filename)
    mime = (content_type or guessed or "application/octet-stream").split(";")[0].strip()
    return mime


def validate_upload(
    *,
    filename: str,
    file_obj: BinaryIO,
    content_type: str | None = None,
) -> tuple[str, str, int]:
    """
    Valide un fichier uploadé.

    Returns:
        (mime_type, checksum, size)
    """
    if not filename:
        raise ValidationError({"file": _("Nom de fichier manquant.")})

    mime = detect_mime_type(filename, content_type)
    if mime not in get_allowed_mime_types():
        raise ValidationError(
            {"file": _("Type de fichier non autorisé (%(mime)s).") % {"mime": mime}}
        )

    checksum, size = compute_checksum(file_obj)
    max_bytes = get_max_upload_bytes()
    if size <= 0:
        raise ValidationError({"file": _("Fichier vide.")})
    if size > max_bytes:
        raise ValidationError(
            {
                "file": _("Fichier trop volumineux (max %(max)s Mo).")
                % {"max": max_bytes // (1024 * 1024)}
            }
        )
    return mime, checksum, size


def assert_matter_in_cabinet(*, matter: Matter, cabinet: Cabinet) -> None:
    """Garantit que le dossier appartient au cabinet courant."""
    if matter.cabinet_id != cabinet.pk:
        raise PermissionDenied(_("Dossier inaccessible."))


def can_preview(mime_type: str) -> bool:
    """Indique si un aperçu inline est possible."""
    if mime_type in PREVIEWABLE_MIME_TYPES:
        return True
    return mime_type.startswith(PREVIEWABLE_MIME_PREFIXES)


@transaction.atomic
def create_document_with_file(
    *,
    cabinet: Cabinet,
    matter: Matter,
    user: User,
    title: str,
    uploaded_file: BinaryIO,
    filename: str,
    content_type: str | None = None,
    description: str = "",
    tags: list[str] | None = None,
) -> Document:
    """Crée un document et sa première version."""
    require_cabinet_perm(user=user, cabinet=cabinet, perm=PERM_ADD)
    assert_matter_in_cabinet(matter=matter, cabinet=cabinet)
    from apps.procurations.services import require_matter_activity_allowed

    require_matter_activity_allowed(matter)

    mime, checksum, size = validate_upload(
        filename=filename,
        file_obj=uploaded_file,
        content_type=content_type,
    )

    document = Document.objects.create(
        cabinet=cabinet,
        matter=matter,
        title=title.strip() or filename,
        description=description.strip(),
        tags=normalize_tags(tags),
        created_by=user,
    )
    version = DocumentVersion(
        cabinet=cabinet,
        document=document,
        version_number=1,
        original_filename=filename[:255],
        checksum=checksum,
        size=size,
        mime_type=mime,
        uploaded_by=user,
        created_by=user,
    )
    version.file.save(filename, uploaded_file, save=False)
    version.save()

    document.current_version = version
    document.save(update_fields=["current_version", "updated_at"])
    logger.info(
        "Document créé id=%s matter=%s cabinet=%s user=%s",
        document.pk,
        matter.pk,
        cabinet.pk,
        user.pk,
    )
    return document


@transaction.atomic
def add_document_version(
    *,
    document: Document,
    user: User,
    uploaded_file: BinaryIO,
    filename: str,
    content_type: str | None = None,
    change_note: str = "",
) -> DocumentVersion:
    """Ajoute une nouvelle version et la définit comme courante."""
    require_cabinet_perm(user=user, cabinet=document.cabinet, perm=PERM_CHANGE)
    from apps.procurations.services import require_matter_activity_allowed

    require_matter_activity_allowed(document.matter)

    mime, checksum, size = validate_upload(
        filename=filename,
        file_obj=uploaded_file,
        content_type=content_type,
    )

    last = (
        DocumentVersion.unscoped.filter(document=document, is_deleted=False)
        .order_by("-version_number")
        .values_list("version_number", flat=True)
        .first()
    )
    next_number = int(last or 0) + 1

    version = DocumentVersion(
        cabinet=document.cabinet,
        document=document,
        version_number=next_number,
        original_filename=filename[:255],
        checksum=checksum,
        size=size,
        mime_type=mime,
        uploaded_by=user,
        created_by=user,
        change_note=change_note.strip()[:255],
    )
    version.file.save(filename, uploaded_file, save=False)
    version.save()

    document.current_version = version
    document.save(update_fields=["current_version", "updated_at"])
    logger.info(
        "Version ajoutée document=%s v=%s user=%s",
        document.pk,
        next_number,
        user.pk,
    )
    return version


def get_document_for_user(*, document_id: str, user: User, cabinet: Cabinet) -> Document:
    """Charge un document du cabinet courant ou lève PermissionDenied/404."""
    require_cabinet_perm(user=user, cabinet=cabinet, perm=PERM_VIEW)
    try:
        return (
            Document.objects.select_related(
                "matter",
                "current_version",
                "current_version__uploaded_by",
            )
            .prefetch_related("versions")
            .get(pk=document_id, cabinet=cabinet)
        )
    except Document.DoesNotExist as exc:
        raise Document.DoesNotExist from exc


def get_version_for_download(
    *,
    version_id: str,
    user: User,
    cabinet: Cabinet,
) -> DocumentVersion:
    """Charge une version téléchargeable du cabinet courant."""
    require_cabinet_perm(user=user, cabinet=cabinet, perm=PERM_VIEW)
    try:
        return DocumentVersion.objects.select_related("document", "document__matter").get(
            pk=version_id,
            cabinet=cabinet,
        )
    except DocumentVersion.DoesNotExist as exc:
        raise DocumentVersion.DoesNotExist from exc


@transaction.atomic
def soft_delete_document(*, document: Document, user: User) -> None:
    """Soft-delete du document et de ses versions."""
    require_cabinet_perm(user=user, cabinet=document.cabinet, perm=PERM_DELETE)
    for version in DocumentVersion.unscoped.filter(document=document, is_deleted=False):
        version.soft_delete()
    document.soft_delete()
    logger.info("Document soft-deleted id=%s user=%s", document.pk, user.pk)


def update_document_metadata(
    *,
    document: Document,
    user: User,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
) -> Document:
    """Met à jour les métadonnées (pas le fichier)."""
    require_cabinet_perm(user=user, cabinet=document.cabinet, perm=PERM_CHANGE)
    document.title = title.strip()
    document.description = description.strip()
    document.tags = normalize_tags(tags)
    document.save(update_fields=["title", "description", "tags", "updated_at"])
    return document
