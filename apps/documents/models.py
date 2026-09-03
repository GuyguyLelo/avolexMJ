"""Modèles GED : documents versionnés rattachés à un dossier."""

from __future__ import annotations

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TenantOwnedModel
from apps.documents.storage import private_document_storage


def document_upload_to(instance: DocumentVersion, filename: str) -> str:
    """
    Chemin de stockage opaque : cabinet/document/version/uuid_filename.

    Le nom original est conservé en base, pas dans le chemin.
    """
    import uuid
    from pathlib import PurePosixPath

    ext = PurePosixPath(filename).suffix.lower()[:16]
    safe_name = f"{uuid.uuid4().hex}{ext}"
    return f"{instance.cabinet_id}/{instance.document_id}/v{instance.version_number}/{safe_name}"


class Document(TenantOwnedModel):
    """Métadonnée d'un document rattaché à un dossier."""

    matter = models.ForeignKey(
        "matters.Matter",
        verbose_name=_("dossier"),
        on_delete=models.CASCADE,
        related_name="documents",
    )
    title = models.CharField(_("titre"), max_length=255)
    description = models.TextField(_("description"), blank=True)
    tags = ArrayField(
        models.CharField(max_length=64),
        verbose_name=_("tags"),
        default=list,
        blank=True,
        help_text=_("Tags libres (ex. : contrat, pièce, correspondance)."),
    )
    current_version = models.ForeignKey(
        "documents.DocumentVersion",
        verbose_name=_("version courante"),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        verbose_name = _("Document")
        verbose_name_plural = _("Documents")
        ordering = ("-updated_at",)
        indexes = [
            models.Index(fields=["cabinet", "matter"], name="documents_doc_cabinet_matter"),
            models.Index(fields=["cabinet", "title"], name="documents_doc_cabinet_title"),
        ]

    def __str__(self) -> str:
        return self.title


class DocumentVersion(TenantOwnedModel):
    """Version immuable d'un fichier (versioning simple)."""

    document = models.ForeignKey(
        Document,
        verbose_name=_("document"),
        on_delete=models.CASCADE,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField(_("numéro de version"))
    file = models.FileField(
        _("fichier"),
        upload_to=document_upload_to,
        storage=private_document_storage,
        max_length=512,
    )
    original_filename = models.CharField(_("nom de fichier original"), max_length=255)
    checksum = models.CharField(_("empreinte SHA-256"), max_length=64, db_index=True)
    size = models.PositiveBigIntegerField(_("taille (octets)"), default=0)
    mime_type = models.CharField(_("type MIME"), max_length=127, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name=_("téléversé par"),
        on_delete=models.SET_NULL,
        null=True,
        related_name="uploaded_document_versions",
    )
    change_note = models.CharField(_("note de version"), max_length=255, blank=True)

    class Meta:
        verbose_name = _("Version de document")
        verbose_name_plural = _("Versions de document")
        ordering = ("-version_number",)
        constraints = [
            models.UniqueConstraint(
                fields=("document", "version_number"),
                condition=models.Q(is_deleted=False),
                name="uniq_document_version_number",
            ),
        ]
        indexes = [
            models.Index(
                fields=["cabinet", "document"],
                name="documents_ver_cabinet_doc",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.document_id} v{self.version_number}"
