"""Vues CRUD et décisions ministérielles — procurations."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q, QuerySet
from django.http import FileResponse, Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _g
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.core.mixins import BreadcrumbMixin
from apps.matters.models import Matter, MatterScale
from apps.procurations.forms import ProcurationDecisionForm, ProcurationForm, ProcurationGrantForm
from apps.procurations.models import Procuration, ProcurationStatus
from apps.procurations.services import (
    create_procuration,
    generate_procuration_instrument,
    get_valid_procuration,
    grant_procuration,
    procurations_queryset,
    procurations_visible_qs,
    refuse_procuration,
    revoke_procuration,
    soft_delete_procuration,
    submit_procuration,
    update_procuration,
)
from apps.tenants.mixins import (
    CabinetPermissionMixin,
    PlatformAdminRequiredMixin,
)
from apps.tenants.models import Cabinet
from apps.tenants.roles import PERM_VIEW
from apps.tenants.services import is_platform_admin, suggest_cabinets_for_practice_area


def _platform_sets_no_cabinet(view: CabinetPermissionMixin, request: Any) -> None:
    """Supervision (SuperAdmin / Synthia) : lecture sans cabinet courant."""
    if is_platform_admin(request.user):
        view.cabinet_required = False
    else:
        view.cabinet_required = True


def _get_procuration(request: HttpRequest, pk: str) -> Procuration:
    """Charge une procuration visible par l'utilisateur (tous cabinets pour le ministère)."""
    qs = procurations_visible_qs(
        user=request.user,  # type: ignore[arg-type]
        cabinet=getattr(request, "cabinet", None),
    )
    return get_object_or_404(qs, pk=pk)


def _selected_create_cabinet_id(
    request: HttpRequest,
    *,
    cabinets: QuerySet[Cabinet],
) -> str:
    """Cabinet choisi dans le formulaire (GET/POST), le dossier prérempli, ou le seul cabinet visible."""
    allowed = [str(pk) for pk in cabinets.values_list("pk", flat=True)]
    allowed_ids = set(allowed)
    matter_id = request.GET.get("matter", "")
    cabinet_id = (request.POST.get("cabinet") or request.GET.get("cabinet") or "").strip()
    if cabinet_id not in allowed_ids:
        cabinet_id = ""
    if not cabinet_id and matter_id:
        matter = Matter.unscoped.filter(pk=matter_id).only("cabinet_id").first()
        if matter is not None and str(matter.cabinet_id) in allowed_ids:
            cabinet_id = str(matter.cabinet_id)
    if not cabinet_id and len(allowed) == 1:
        cabinet_id = allowed[0]
    return cabinet_id


class ProcurationListView(CabinetPermissionMixin, BreadcrumbMixin, ListView):
    """Liste paginée des procurations."""

    template_name = "procurations/procuration_list.html"
    context_object_name = "procurations"
    paginate_by = 10
    required_perm = PERM_VIEW
    cabinet_required = False

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        _platform_sets_no_cabinet(self, request)
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [{"label": _g("Procurations")}]

    def get_queryset(self) -> QuerySet[Procuration]:
        platform = is_platform_admin(self.request.user)  # type: ignore[arg-type]
        return procurations_queryset(
            cabinet=self.request.cabinet,  # type: ignore[attr-defined]
            q=self.request.GET.get("q", ""),
            status=self.request.GET.get("status", ""),
            matter_id=self.request.GET.get("matter", ""),
            scale=self.request.GET.get("scale", ""),
            cabinet_id=self.request.GET.get("cabinet", ""),
            cross_cabinet=platform,
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        platform = is_platform_admin(self.request.user)  # type: ignore[arg-type]
        ctx["filter_q"] = self.request.GET.get("q", "")
        ctx["filter_status"] = self.request.GET.get("status", "")
        ctx["filter_matter"] = self.request.GET.get("matter", "")
        ctx["filter_scale"] = self.request.GET.get("scale", "")
        ctx["filter_cabinet"] = self.request.GET.get("cabinet", "")
        ctx["status_choices"] = ProcurationStatus.choices
        ctx["scale_choices"] = MatterScale.choices
        if platform:
            ctx["matters"] = Matter.objects.none()
            ctx["cabinets"] = Cabinet.objects.filter(is_active=True).order_by("name")
        else:
            ctx["matters"] = Matter.objects.order_by("-updated_at")
            ctx["cabinets"] = []
        return ctx


class ProcurationDetailView(CabinetPermissionMixin, BreadcrumbMixin, DetailView):
    """Fiche procuration + actions ministère."""

    template_name = "procurations/procuration_detail.html"
    context_object_name = "procuration"
    required_perm = PERM_VIEW
    cabinet_required = False

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        _platform_sets_no_cabinet(self, request)
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self) -> QuerySet[Procuration]:
        return procurations_visible_qs(
            user=self.request.user,  # type: ignore[arg-type]
            cabinet=getattr(self.request, "cabinet", None),
        )

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Procurations"), "url": reverse("procurations:list")},
            {"label": self.object.reference},
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        procuration: Procuration = self.object
        platform = is_platform_admin(self.request.user)  # type: ignore[arg-type]
        ctx["grant_form"] = ProcurationGrantForm()
        ctx["decision_form"] = ProcurationDecisionForm()
        ctx["can_submit"] = False
        ctx["can_edit"] = False
        ctx["can_delete"] = False
        ctx["can_grant"] = platform and procuration.is_pending
        ctx["can_refuse"] = platform and procuration.is_pending
        ctx["can_generate"] = platform and procuration.status == ProcurationStatus.GRANTED
        ctx["valid_for_matter"] = (
            get_valid_procuration(procuration.matter) if procuration.matter_id else None
        )
        return ctx


class ProcurationCreateView(PlatformAdminRequiredMixin, BreadcrumbMixin, CreateView):
    """Le ministère délivre une procuration à un cabinet pour un dossier."""

    template_name = "procurations/procuration_form.html"
    form_class = ProcurationForm
    cabinet_required = False

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Procurations"), "url": reverse("procurations:list")},
            {"label": _g("Délivrer une procuration")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        # Afficher uniquement les dossiers sans procuration valide
        from apps.procurations.services import get_valid_procuration
        matters_with_procuration = set()
        for proc in Procuration.objects.filter(status=ProcurationStatus.GRANTED).select_related('matter'):
            if proc.matter_id:
                matters_with_procuration.add(proc.matter_id)
        
        matter_queryset = (
            Matter.unscoped
            .filter(is_archived=False, cabinet__isnull=True)
            .exclude(pk__in=matters_with_procuration)
            .select_related("responsible_lawyer")
            .order_by("-updated_at")
        )
        # Si un cabinet est déjà choisi (GET), inclure aussi ses dossiers sans procuration.
        cabinet_id = self.request.GET.get("cabinet") or self.request.POST.get("cabinet")
        if cabinet_id:
            matter_queryset = (
                Matter.unscoped
                .filter(is_archived=False)
                .filter(Q(cabinet__isnull=True) | Q(cabinet_id=cabinet_id))
                .exclude(pk__in=matters_with_procuration)
                .select_related("responsible_lawyer")
                .order_by("-updated_at")
            )
        
        kwargs["matter_queryset"] = matter_queryset
        kwargs["cabinet_queryset"] = Cabinet.objects.filter(is_active=True).order_by("name")
        kwargs["include_cabinet"] = True
        return kwargs

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        matter_id = self.request.GET.get("matter", "")
        if matter_id:
            initial["matter"] = matter_id
        return initial

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        # Suggérer des cabinets spécialisés selon la matière du dossier sélectionné
        ctx["suggested_cabinets"] = []
        if self.request.GET.get("matter"):
            matter = Matter.unscoped.filter(pk=self.request.GET.get("matter")).first()
            if matter and matter.practice_area:
                ctx["suggested_cabinets"] = suggest_cabinets_for_practice_area(
                    practice_area_name=matter.practice_area
                )
        return ctx

    def form_valid(self, form: ProcurationForm) -> HttpResponse:
        try:
            procuration = create_procuration(
                cabinet=form.cleaned_data["cabinet"],
                user=self.request.user,  # type: ignore[arg-type]
                matter=form.cleaned_data["matter"],
                notes=form.cleaned_data.get("notes") or "",
                instrument=form.cleaned_data.get("instrument"),
            )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError) and hasattr(exc, "message_dict"):
                for field, errs in exc.message_dict.items():
                    for err in errs:
                        form.add_error(field if field != "__all__" else None, err)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(
            self.request,
            _g("Procuration délivrée au cabinet. Le dossier est autorisé."),
        )
        return redirect("procurations:detail", pk=procuration.pk)


class ProcurationUpdateView(PlatformAdminRequiredMixin, BreadcrumbMixin, UpdateView):
    """Édition d'une procuration historique encore en attente."""

    template_name = "procurations/procuration_form.html"
    form_class = ProcurationForm
    context_object_name = "procuration"
    cabinet_required = False

    def get_queryset(self) -> QuerySet[Procuration]:
        return procurations_visible_qs(
            user=self.request.user,  # type: ignore[arg-type]
            cabinet=getattr(self.request, "cabinet", None),
        )

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Procurations"), "url": reverse("procurations:list")},
            {
                "label": self.object.reference,
                "url": reverse("procurations:detail", args=[self.object.pk]),
            },
            {"label": _g("Modifier")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["include_cabinet"] = False
        kwargs["matter_queryset"] = Matter.unscoped.filter(pk=self.object.matter_id)
        return kwargs

    def form_valid(self, form: ProcurationForm) -> HttpResponse:
        submit = self.request.POST.get("submit_now") == "1"
        try:
            procuration = update_procuration(
                procuration=self.object,
                user=self.request.user,  # type: ignore[arg-type]
                notes=form.cleaned_data.get("notes") or "",
                instrument=form.cleaned_data.get("instrument"),
            )
            if submit and procuration.status == ProcurationStatus.DRAFT:
                procuration = submit_procuration(
                    procuration=procuration,
                    user=self.request.user,  # type: ignore[arg-type]
                )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError) and hasattr(exc, "message_dict"):
                for field, errs in exc.message_dict.items():
                    for err in errs:
                        form.add_error(field if field != "__all__" else None, err)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        if submit:
            messages.success(self.request, _g("Demande transmise au Ministère de la Justice."))
        else:
            messages.success(self.request, _g("Procuration mise à jour."))
        return redirect("procurations:detail", pk=self.object.pk)


class ProcurationSubmitView(PlatformAdminRequiredMixin, View):
    """Transmet une ancienne demande brouillon."""

    cabinet_required = False
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        procuration = _get_procuration(request, pk)
        try:
            submit_procuration(procuration=procuration, user=request.user)  # type: ignore[arg-type]
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect("procurations:detail", pk=pk)
        messages.success(request, _g("Demande transmise au Ministère de la Justice."))
        return redirect("procurations:detail", pk=pk)


class ProcurationDeleteView(PlatformAdminRequiredMixin, View):
    """Suppression logique d'une procuration non accordée."""

    cabinet_required = False
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        procuration = _get_procuration(request, pk)
        try:
            soft_delete_procuration(procuration=procuration, user=request.user)  # type: ignore[arg-type]
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect("procurations:detail", pk=pk)
        messages.success(request, _g("Procuration supprimée."))
        return redirect("procurations:list")


class ProcurationGrantView(PlatformAdminRequiredMixin, View):
    """Octroi par le Ministère de la Justice."""

    cabinet_required = False
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        procuration = _get_procuration(request, pk)
        form = ProcurationGrantForm(request.POST)
        if not form.is_valid():
            messages.error(request, _g("Vérifiez les champs d'octroi."))
            return redirect("procurations:detail", pk=pk)
        try:
            grant_procuration(
                procuration=procuration,
                actor=request.user,  # type: ignore[arg-type]
                ministry_reference=form.cleaned_data.get("ministry_reference") or "",
                valid_from=form.cleaned_data.get("valid_from"),
                expires_at=form.cleaned_data.get("expires_at"),
                notes=form.cleaned_data.get("notes") or "",
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect("procurations:detail", pk=pk)
        messages.success(request, _g("Procuration accordée. Le cabinet peut agir sur le dossier."))
        return redirect("procurations:detail", pk=pk)


class ProcurationRefuseView(PlatformAdminRequiredMixin, View):
    """Refus ministériel."""

    cabinet_required = False
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        procuration = _get_procuration(request, pk)
        form = ProcurationDecisionForm(request.POST)
        if not form.is_valid():
            messages.error(request, _g("Le motif du refus est obligatoire."))
            return redirect("procurations:detail", pk=pk)
        try:
            refuse_procuration(
                procuration=procuration,
                actor=request.user,  # type: ignore[arg-type]
                reason=form.cleaned_data["reason"],
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect("procurations:detail", pk=pk)
        messages.success(request, _g("Procuration refusée."))
        return redirect("procurations:detail", pk=pk)


class ProcurationRevokeView(PlatformAdminRequiredMixin, View):
    """Révocation ministérielle."""

    cabinet_required = False
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        procuration = _get_procuration(request, pk)
        form = ProcurationDecisionForm(request.POST)
        if not form.is_valid():
            messages.error(request, _g("Le motif de révocation est obligatoire."))
            return redirect("procurations:detail", pk=pk)
        try:
            revoke_procuration(
                procuration=procuration,
                actor=request.user,  # type: ignore[arg-type]
                reason=form.cleaned_data["reason"],
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect("procurations:detail", pk=pk)
        messages.success(request, _g("Procuration révoquée. Les activités sur le dossier sont bloquées."))
        return redirect("procurations:detail", pk=pk)


class ProcurationGenerateView(PlatformAdminRequiredMixin, View):
    """Génère l'acte PDF de la procuration accordée."""

    cabinet_required = False
    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        procuration = _get_procuration(request, pk)
        try:
            generate_procuration_instrument(
                procuration=procuration,
                actor=request.user,  # type: ignore[arg-type]
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect("procurations:detail", pk=pk)
        messages.success(request, _g("Acte de procuration généré."))
        return redirect("procurations:detail", pk=pk)


class ProcurationDownloadView(CabinetPermissionMixin, View):
    """Téléchargement de l'acte scanné."""

    required_perm = PERM_VIEW
    cabinet_required = False
    http_method_names = ("get",)

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        _platform_sets_no_cabinet(self, request)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, pk: str) -> HttpResponse:
        procuration = _get_procuration(request, pk)
        return _serve_instrument(procuration, as_attachment=True)


class ProcurationPreviewView(CabinetPermissionMixin, View):
    """Affichage inline de l'acte scanné (PDF / image)."""

    required_perm = PERM_VIEW
    cabinet_required = False
    http_method_names = ("get",)

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        _platform_sets_no_cabinet(self, request)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: HttpRequest, pk: str) -> HttpResponse:
        procuration = _get_procuration(request, pk)
        if not procuration.instrument:
            raise Http404(_g("Aucun acte n'est joint à cette procuration."))
        if not procuration.instrument_can_preview:
            return redirect("procurations:download", pk=pk)
        return _serve_instrument(procuration, as_attachment=False)


def _serve_instrument(procuration: Procuration, *, as_attachment: bool) -> FileResponse:
    """Sert l'acte joint en téléchargement ou en aperçu."""
    if not procuration.instrument:
        raise Http404(_g("Aucun acte n'est joint à cette procuration."))
    filename = procuration.instrument_filename or "acte-procuration.pdf"
    response = FileResponse(
        procuration.instrument.open("rb"),
        as_attachment=as_attachment,
        filename=filename,
        content_type=procuration.instrument_mime_type,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    if not as_attachment:
        response["Content-Security-Policy"] = (
            "default-src 'none'; img-src 'self' data:; style-src 'none'; sandbox"
        )
    return response
