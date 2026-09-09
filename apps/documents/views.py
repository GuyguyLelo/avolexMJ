"""Vues GED — accès contrôlé, fichiers jamais exposés publiquement."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Prefetch, QuerySet
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _g, gettext_lazy as _
from django.views import View
from django.views.generic import DetailView, FormView, ListView

from apps.core.mixins import BreadcrumbMixin
from apps.documents.forms import DocumentMetadataForm, DocumentUploadForm, DocumentVersionForm
from apps.documents.models import Document, DocumentVersion
from apps.documents.services import (
    add_document_version,
    can_preview,
    create_document_with_file,
    get_version_for_download,
    soft_delete_document,
    update_document_metadata,
)
from apps.matters.models import Matter
from apps.tenants.mixins import CabinetPermissionMixin
from apps.tenants.roles import PERM_ADD, PERM_CHANGE, PERM_DELETE, PERM_VIEW


class DocumentListView(CabinetPermissionMixin, BreadcrumbMixin, ListView):
    """Liste des documents du cabinet (filtre dossier / tag)."""

    template_name = "documents/document_list.html"
    context_object_name = "documents"
    paginate_by = 10
    required_perm = PERM_VIEW

    def get_breadcrumb(self) -> list[dict[str, str]]:
        """Fil d'Ariane."""
        return [{"label": _g("Documents")}]

    def get_queryset(self) -> QuerySet[Document]:
        """Documents du cabinet avec version courante."""
        qs = Document.objects.select_related(
            "matter",
            "current_version",
            "current_version__uploaded_by",
        ).order_by("-updated_at")
        matter_id = self.request.GET.get("matter")
        if matter_id:
            qs = qs.filter(matter_id=matter_id)
        tag = (self.request.GET.get("tag") or "").strip().lower()
        if tag:
            qs = qs.filter(tags__contains=[tag])
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(title__icontains=q)
        return qs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Ajoute les dossiers pour le filtre."""
        ctx = super().get_context_data(**kwargs)
        ctx["matters"] = Matter.objects.order_by("reference")
        ctx["filter_matter"] = self.request.GET.get("matter", "")
        ctx["filter_tag"] = self.request.GET.get("tag", "")
        ctx["filter_q"] = self.request.GET.get("q", "")
        return ctx


class DocumentUploadView(CabinetPermissionMixin, BreadcrumbMixin, FormView):
    """Téléversement d'un nouveau document."""

    template_name = "documents/document_upload.html"
    form_class = DocumentUploadForm
    required_perm = PERM_ADD

    def get_breadcrumb(self) -> list[dict[str, str]]:
        """Fil d'Ariane upload."""
        return [
            {"label": _g("Documents"), "url": reverse("documents:list")},
            {"label": _g("Téléverser")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        """Passe le queryset des dossiers du cabinet."""
        kwargs = super().get_form_kwargs()
        kwargs["matter_queryset"] = Matter.objects.select_related("responsible_lawyer", "cabinet").order_by("reference")
        return kwargs

    def get_initial(self) -> dict[str, Any]:
        """Pré-sélectionne un dossier si fourni en querystring."""
        initial = super().get_initial()
        matter_id = self.request.GET.get("matter")
        if matter_id:
            initial["matter"] = matter_id
        return initial

    def form_valid(self, form: DocumentUploadForm) -> HttpResponse:
        """Crée le document via le service."""
        uploaded = form.cleaned_data["file"]
        cabinet = self.request.cabinet  # type: ignore[attr-defined]
        try:
            document = create_document_with_file(
                cabinet=cabinet,
                matter=form.cleaned_data["matter"],
                user=self.request.user,  # type: ignore[arg-type]
                title=form.cleaned_data.get("title") or uploaded.name,
                uploaded_file=uploaded,
                filename=uploaded.name,
                content_type=getattr(uploaded, "content_type", None),
                description=form.cleaned_data.get("description") or "",
                tags=form.cleaned_tags(),
            )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError) and hasattr(exc, "message_dict"):
                for field, errs in exc.message_dict.items():
                    for err in errs:
                        form.add_error(field if field in form.fields else None, err)
            else:
                form.add_error(None, exc)
            return self.form_invalid(form)

        messages.success(self.request, _("Document téléversé."))
        return redirect("documents:detail", pk=document.pk)


class DocumentDetailView(CabinetPermissionMixin, BreadcrumbMixin, DetailView):
    """Détail, versions, aperçu et actions."""

    template_name = "documents/document_detail.html"
    context_object_name = "document"
    required_perm = PERM_VIEW

    def get_queryset(self) -> QuerySet[Document]:
        """Document + versions (prefetch)."""
        return Document.objects.select_related(
            "matter",
            "matter",
            "assigned_to",
            "current_version",
            "current_version__uploaded_by",
        ).prefetch_related(
            Prefetch(
                "versions",
                queryset=DocumentVersion.objects.select_related("uploaded_by").order_by(
                    "-version_number"
                ),
            )
        )

    def get_breadcrumb(self) -> list[dict[str, str]]:
        """Fil d'Ariane détail."""
        crumbs: list[dict[str, str]] = [
            {"label": _g("Documents"), "url": reverse("documents:list")},
        ]
        document = getattr(self, "object", None)
        if document is not None:
            crumbs.append({"label": document.title})
        return crumbs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Formulaires secondaires + preview flag."""
        ctx = super().get_context_data(**kwargs)
        document: Document = self.object
        current = document.current_version
        ctx["can_preview"] = bool(current and can_preview(current.mime_type))
        ctx["version_form"] = DocumentVersionForm()
        return ctx


class DocumentUpdateMetadataView(CabinetPermissionMixin, View):
    """POST métadonnées."""

    required_perm = PERM_CHANGE
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Met à jour titre / description / tags."""
        document = get_object_or_404(
            Document.objects.select_related("cabinet"),
            pk=pk,
        )
        form = DocumentMetadataForm(request.POST)
        if not form.is_valid():
            messages.error(request, _("Formulaire invalide."))
            return redirect("documents:detail", pk=pk)
        try:
            update_document_metadata(
                document=document,
                user=request.user,  # type: ignore[arg-type]
                title=form.cleaned_data["title"],
                description=form.cleaned_data.get("description") or "",
                tags=form.cleaned_tags(),
            )
        except PermissionDenied:
            raise
        messages.success(request, _("Métadonnées enregistrées."))
        return redirect("documents:detail", pk=pk)


class DocumentAddVersionView(CabinetPermissionMixin, View):
    """POST nouvelle version."""

    required_perm = PERM_CHANGE
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Ajoute une version."""
        document = get_object_or_404(Document, pk=pk)
        form = DocumentVersionForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, _("Fichier invalide."))
            return redirect("documents:detail", pk=pk)
        uploaded = form.cleaned_data["file"]
        try:
            add_document_version(
                document=document,
                user=request.user,  # type: ignore[arg-type]
                uploaded_file=uploaded,
                filename=uploaded.name,
                content_type=getattr(uploaded, "content_type", None),
                change_note=form.cleaned_data.get("change_note") or "",
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect("documents:detail", pk=pk)
        messages.success(request, _("Nouvelle version enregistrée."))
        return redirect("documents:detail", pk=pk)


class DocumentDeleteView(CabinetPermissionMixin, View):
    """Soft-delete d'un document."""

    required_perm = PERM_DELETE
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        """Supprime (soft) le document."""
        document = get_object_or_404(Document, pk=pk)
        soft_delete_document(document=document, user=request.user)  # type: ignore[arg-type]
        messages.success(request, _("Document supprimé."))
        return redirect("documents:list")


class DocumentDownloadView(CabinetPermissionMixin, View):
    """Téléchargement protégé d'une version (attachment)."""

    required_perm = PERM_VIEW
    http_method_names = ("get",)

    def get(self, request: HttpRequest, version_id: str) -> HttpResponse:
        """Sert le fichier en attachment."""
        cabinet = request.cabinet  # type: ignore[attr-defined]
        try:
            version = get_version_for_download(
                version_id=version_id,
                user=request.user,  # type: ignore[arg-type]
                cabinet=cabinet,
            )
        except DocumentVersion.DoesNotExist as exc:
            raise Http404(_("Version introuvable.")) from exc

        response = FileResponse(
            version.file.open("rb"),
            as_attachment=True,
            filename=version.original_filename,
            content_type=version.mime_type or "application/octet-stream",
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response


class DocumentPreviewView(CabinetPermissionMixin, View):
    """Aperçu inline (PDF / images / texte) — même contrôle d'accès."""

    required_perm = PERM_VIEW
    http_method_names = ("get",)

    def get(self, request: HttpRequest, version_id: str) -> HttpResponse:
        """Sert le fichier en inline si prévisualisable."""
        cabinet = request.cabinet  # type: ignore[attr-defined]
        try:
            version = get_version_for_download(
                version_id=version_id,
                user=request.user,  # type: ignore[arg-type]
                cabinet=cabinet,
            )
        except DocumentVersion.DoesNotExist as exc:
            raise Http404(_("Version introuvable.")) from exc

        if not can_preview(version.mime_type):
            return redirect("documents:download", version_id=version.pk)

        response = FileResponse(
            version.file.open("rb"),
            as_attachment=False,
            filename=version.original_filename,
            content_type=version.mime_type or "application/octet-stream",
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = (
            "default-src 'none'; img-src 'self' data:; style-src 'none'; sandbox"
        )
        response["Cache-Control"] = "private, no-store"
        return response
