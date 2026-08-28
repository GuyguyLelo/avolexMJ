"""Vues CRUD dossiers."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import QuerySet
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _g
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.calendar_app.models import EventType, HearingStatus
from apps.clients.models import Client
from apps.core.mixins import BreadcrumbMixin
from apps.matters.forms import MatterForm
from apps.matters.models import Matter, MatterScale, MatterStatus
from apps.matters.services import (
    archive_matter,
    create_matter,
    matters_queryset,
    soft_delete_matter,
    update_matter,
)
from apps.tenants.mixins import CabinetPermissionMixin
from apps.tenants.models import Cabinet, Membership
from apps.tenants.roles import PERM_ADD, PERM_CHANGE, PERM_DELETE, PERM_VIEW, Role
from apps.tenants.services import (
    is_platform_admin,
    set_session_cabinet,
    suggest_cabinets_for_practice_area,
)


def _visible_matters(request: Any) -> QuerySet[Matter]:
    """Dossiers accessibles : tous pour le ministère, procuration valide pour le cabinet."""
    qs = Matter.objects.select_related("client", "responsible_lawyer")
    cabinet = getattr(request, "cabinet", None)
    if cabinet is not None and not is_platform_admin(request.user):
        from apps.procurations.services import authorized_matter_ids_for_cabinet

        qs = qs.filter(pk__in=authorized_matter_ids_for_cabinet(cabinet=cabinet))
    return qs


class MatterListView(CabinetPermissionMixin, BreadcrumbMixin, ListView):
    """Liste paginée + filtres."""

    template_name = "matters/matter_list.html"
    context_object_name = "matters"
    paginate_by = 10
    required_perm = PERM_VIEW

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [{"label": _g("Dossiers")}]

    def get_queryset(self) -> QuerySet[Matter]:
        return matters_queryset(
            cabinet=self.request.cabinet,  # type: ignore[attr-defined]
            user=self.request.user,  # type: ignore[arg-type]
            q=self.request.GET.get("q", ""),
            status=self.request.GET.get("status", ""),
            client_id=self.request.GET.get("client", ""),
            archived=self.request.GET.get("archived", ""),
            scale=self.request.GET.get("scale", ""),
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["filter_q"] = self.request.GET.get("q", "")
        ctx["filter_status"] = self.request.GET.get("status", "")
        ctx["filter_client"] = self.request.GET.get("client", "")
        ctx["filter_archived"] = self.request.GET.get("archived", "")
        ctx["filter_scale"] = self.request.GET.get("scale", "")
        ctx["status_choices"] = MatterStatus.choices
        ctx["scale_choices"] = MatterScale.choices
        ctx["clients"] = Client.objects.order_by("last_name", "company_name")
        return ctx


class MatterDetailView(CabinetPermissionMixin, BreadcrumbMixin, DetailView):
    """Fiche dossier + historique d'actions."""

    template_name = "matters/matter_detail.html"
    context_object_name = "matter"
    required_perm = PERM_VIEW

    def get_queryset(self) -> QuerySet[Matter]:
        return _visible_matters(self.request)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Dossiers"), "url": reverse("matters:list")},
            {"label": self.object.reference},
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["actions"] = self.object.actions.select_related("actor").all()[:50]
        matter: Matter = self.object
        ctx["can_delete_matter"] = not matter.is_treated
        ctx["can_archive_matter"] = matter.status == MatterStatus.CLOSED and not matter.is_archived
        now = timezone.now()
        ctx["upcoming_hearings"] = (
            matter.events.filter(
                event_type=EventType.HEARING,
                starts_at__gte=now,
                hearing_status__in=(HearingStatus.SCHEDULED, ""),
            )
            .select_related("assigned_to")
            .order_by("starts_at")[:10]
        )
        from apps.procurations.services import get_valid_procuration, matter_has_valid_procuration

        ctx["has_valid_procuration"] = matter_has_valid_procuration(matter)
        ctx["valid_procuration"] = get_valid_procuration(matter)
        ctx["latest_procuration"] = (
            matter.procurations.select_related("granted_by").order_by("-created_at").first()
        )
        ctx["display_procuration"] = ctx["valid_procuration"] or ctx["latest_procuration"]
        return ctx


def _lawyer_queryset(cabinet: Any) -> QuerySet[Any]:
    from django.contrib.auth import get_user_model

    if cabinet is None:
        return get_user_model().objects.none()
    user_ids = Membership.objects.filter(
        cabinet=cabinet,
        is_active=True,
        role__in=(Role.CAIMAN, Role.LAWYER),
    ).values_list("user_id", flat=True)

    return get_user_model().objects.filter(pk__in=user_ids).order_by("last_name", "email")


def _client_queryset(cabinet: Any) -> QuerySet[Client]:
    if cabinet is None:
        return Client.objects.none()
    return Client.objects.for_cabinet(cabinet).order_by("last_name", "company_name")


def _resolve_target_cabinet(request: Any, *, use_current: bool = False) -> Any:
    raw = request.POST.get("target_cabinet") or request.GET.get("cabinet")
    if raw:
        cabinet = Cabinet.objects.filter(pk=raw, is_active=True).first()
        if cabinet is not None:
            return cabinet
    if use_current:
        return getattr(request, "cabinet", None)
    return None


class MatterCreateView(CabinetPermissionMixin, BreadcrumbMixin, CreateView):
    """Création dossier — ministère uniquement."""

    template_name = "matters/matter_form.html"
    form_class = MatterForm
    required_perm = PERM_ADD
    platform_write = True

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not is_platform_admin(request.user):
            raise PermissionDenied(_g("Seul le Ministère de la Justice peut ouvrir un dossier."))
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Dossiers"), "url": reverse("matters:list")},
            {"label": _g("Nouveau dossier")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        cabinet = _resolve_target_cabinet(self.request)
        kwargs["client_queryset"] = _client_queryset(cabinet)
        kwargs["lawyer_queryset"] = _lawyer_queryset(cabinet)
        kwargs["include_cabinet"] = True
        kwargs["cabinets"] = Cabinet.objects.filter(is_active=True).order_by("name")
        return kwargs

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        cabinet = _resolve_target_cabinet(self.request)
        if cabinet is not None:
            initial["target_cabinet"] = cabinet
        practice_area = self.request.GET.get("practice_area") or ""
        if practice_area:
            initial["practice_area"] = practice_area
        client_id = self.request.GET.get("client")
        if client_id:
            initial["client"] = client_id
        lawyers = _lawyer_queryset(cabinet)
        if lawyers.filter(pk=self.request.user.pk).exists():
            initial["responsible_lawyer"] = self.request.user.pk
        else:
            first_lawyer = lawyers.first()
            if first_lawyer is not None:
                initial["responsible_lawyer"] = first_lawyer.pk
        return initial

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        practice_area = self.request.GET.get("practice_area") or ""
        form = ctx.get("form")
        if form is not None and form.is_bound:
            practice_area = form.data.get("practice_area") or practice_area
        elif form is not None and form.initial.get("practice_area"):
            practice_area = form.initial["practice_area"]
        ctx["suggested_cabinets"] = suggest_cabinets_for_practice_area(
            practice_area_name=practice_area
        )
        ctx["target_cabinet"] = _resolve_target_cabinet(self.request)
        return ctx

    def form_valid(self, form: MatterForm) -> HttpResponse:
        data = form.cleaned_data
        cabinet = data["target_cabinet"]
        try:
            matter = create_matter(
                cabinet=cabinet,
                user=self.request.user,  # type: ignore[arg-type]
                client=data["client"],
                title=data["title"],
                responsible_lawyer=data["responsible_lawyer"],
                description=data.get("description") or "",
                practice_area=data.get("practice_area") or "",
                jurisdiction=data.get("jurisdiction") or "",
                opposing_party=data.get("opposing_party") or "",
                scale=data.get("scale") or MatterScale.NATIONAL,
                status=data.get("status") or MatterStatus.OPEN,
                opened_at=data.get("opened_at"),
                closed_at=data.get("closed_at"),
                notes=data.get("notes") or "",
            )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError) and hasattr(exc, "message_dict"):
                for field, errs in exc.message_dict.items():
                    for err in errs:
                        form.add_error(field if field != "__all__" else None, err)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        set_session_cabinet(self.request, cabinet)
        messages.success(self.request, _g("Dossier créé."))
        return redirect("matters:detail", pk=matter.pk)


class MatterUpdateView(CabinetPermissionMixin, BreadcrumbMixin, UpdateView):
    """Édition dossier."""

    template_name = "matters/matter_form.html"
    form_class = MatterForm
    context_object_name = "matter"
    required_perm = PERM_CHANGE

    def get_queryset(self) -> QuerySet[Matter]:
        return _visible_matters(self.request)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Dossiers"), "url": reverse("matters:list")},
            {
                "label": self.object.reference,
                "url": reverse("matters:detail", args=[self.object.pk]),
            },
            {"label": _g("Modifier")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        cabinet = self.request.cabinet  # type: ignore[attr-defined]
        kwargs["client_queryset"] = _client_queryset(cabinet)
        kwargs["lawyer_queryset"] = _lawyer_queryset(cabinet)
        return kwargs

    def form_valid(self, form: MatterForm) -> HttpResponse:
        try:
            update_matter(
                matter=self.object,
                user=self.request.user,  # type: ignore[arg-type]
                **form.cleaned_data,
            )
        except (ValidationError, PermissionDenied) as exc:
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Dossier mis à jour."))
        return redirect("matters:detail", pk=self.object.pk)


class MatterDeleteView(CabinetPermissionMixin, View):
    """Suppression logique."""

    required_perm = PERM_DELETE
    http_method_names = ("post",)

    def post(self, request: Any, pk: str) -> HttpResponse:
        matter = get_object_or_404(_visible_matters(request), pk=pk)
        try:
            soft_delete_matter(matter=matter, user=request.user)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect("matters:detail", pk=pk)
        messages.success(request, _g("Dossier supprimé."))
        return redirect("matters:list")


class MatterArchiveView(CabinetPermissionMixin, View):
    """Archive un dossier clos."""

    required_perm = PERM_CHANGE
    http_method_names = ("post",)

    def post(self, request: Any, pk: str) -> HttpResponse:
        matter = get_object_or_404(_visible_matters(request), pk=pk)
        try:
            archive_matter(matter=matter, user=request.user)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect("matters:detail", pk=pk)
        messages.success(request, _g("Dossier archivé."))
        return redirect("matters:detail", pk=pk)


class MatterCreateContextView(CabinetPermissionMixin, View):
    """JSON : clients, avocats et cabinets spécialisés pour l'ouverture d'un dossier."""

    required_perm = PERM_ADD
    platform_write = True
    http_method_names = ("get",)

    def get(self, request: Any, *args: Any, **kwargs: Any) -> JsonResponse:
        if not is_platform_admin(request.user):
            raise PermissionDenied(_g("Seul le Ministère de la Justice peut ouvrir un dossier."))
        cabinet = _resolve_target_cabinet(request)
        practice_area = request.GET.get("practice_area") or ""
        clients = [
            {"id": str(item.pk), "label": item.display_name}
            for item in _client_queryset(cabinet)[:200]
        ]
        lawyers = [
            {"id": str(item.pk), "label": item.full_name or item.email}
            for item in _lawyer_queryset(cabinet)
        ]
        suggested = [
            {
                "id": str(item.pk),
                "name": item.name,
                "city": item.city,
                "bar_association": item.bar_association,
            }
            for item in suggest_cabinets_for_practice_area(practice_area_name=practice_area)
        ]
        return JsonResponse(
            {
                "cabinet_id": str(cabinet.pk) if cabinet is not None else "",
                "clients": clients,
                "lawyers": lawyers,
                "suggested_cabinets": suggested,
            }
        )
