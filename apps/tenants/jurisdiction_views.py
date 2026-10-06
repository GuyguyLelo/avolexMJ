"""Vues CRUD du référentiel de juridictions."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _g
from django.views import View
from django.views.generic import FormView, ListView

from apps.core.mixins import BreadcrumbMixin
from apps.tenants.forms import JurisdictionForm
from apps.tenants.jurisdictions import ensure_default_jurisdictions
from apps.tenants.mixins import PlatformAdminRequiredMixin
from apps.tenants.models import Jurisdiction, JurisdictionScale
from apps.tenants.services import create_jurisdiction, delete_jurisdiction, jurisdictions_queryset, update_jurisdiction


def _apply_form_errors(form: JurisdictionForm, exc: ValidationError) -> None:
    if hasattr(exc, "message_dict"):
        for field, errs in exc.message_dict.items():
            for err in errs:
                form.add_error(field if field != "__all__" else None, err)
        return
    form.add_error(None, exc)


class JurisdictionListView(PlatformAdminRequiredMixin, BreadcrumbMixin, ListView):
    """Référentiel des juridictions."""

    template_name = "tenants/jurisdiction_list.html"
    context_object_name = "jurisdictions"
    paginate_by = 25

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Paramètres")},
            {"label": _g("Données référentielles"), "url": reverse("core:settings")},
            {"label": _g("Juridictions")},
        ]

    def get_queryset(self) -> QuerySet[Jurisdiction]:
        ensure_default_jurisdictions()
        return jurisdictions_queryset(
            q=self.request.GET.get("q", ""),
            scale=self.request.GET.get("scale", ""),
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["filter_q"] = self.request.GET.get("q", "")
        ctx["filter_scale"] = self.request.GET.get("scale", "")
        ctx["scale_choices"] = JurisdictionScale.choices
        return ctx


class JurisdictionCreateView(PlatformAdminRequiredMixin, BreadcrumbMixin, FormView):
    """Création d'une juridiction du référentiel."""

    template_name = "tenants/jurisdiction_form.html"
    form_class = JurisdictionForm

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Paramètres")},
            {"label": _g("Données référentielles"), "url": reverse("core:settings")},
            {"label": _g("Juridictions"), "url": reverse("tenants:jurisdiction_list")},
            {"label": _g("Nouvelle juridiction")},
        ]

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        initial.setdefault("is_active", True)
        initial.setdefault("scale", JurisdictionScale.NATIONAL)
        return initial

    def form_valid(self, form: JurisdictionForm) -> HttpResponse:
        data = form.cleaned_data
        try:
            create_jurisdiction(
                actor=self.request.user,  # type: ignore[arg-type]
                name=data["name"],
                scale=data["scale"],
                category=data.get("category") or "",
                is_active=data.get("is_active", True),
            )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError):
                _apply_form_errors(form, exc)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Juridiction créée."))
        return redirect("tenants:jurisdiction_list")


class JurisdictionUpdateView(PlatformAdminRequiredMixin, BreadcrumbMixin, FormView):
    """Édition d'une juridiction du référentiel."""

    template_name = "tenants/jurisdiction_form.html"
    form_class = JurisdictionForm

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.jurisdiction = get_object_or_404(Jurisdiction, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Paramètres")},
            {"label": _g("Données référentielles"), "url": reverse("core:settings")},
            {"label": _g("Juridictions"), "url": reverse("tenants:jurisdiction_list")},
            {"label": self.jurisdiction.name},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.jurisdiction
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["jurisdiction"] = self.jurisdiction
        return ctx

    def form_valid(self, form: JurisdictionForm) -> HttpResponse:
        data = form.cleaned_data
        try:
            update_jurisdiction(
                actor=self.request.user,  # type: ignore[arg-type]
                jurisdiction=self.jurisdiction,
                name=data["name"],
                scale=data["scale"],
                category=data.get("category") or "",
                is_active=data.get("is_active", True),
            )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError):
                _apply_form_errors(form, exc)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Juridiction mise à jour."))
        return redirect("tenants:jurisdiction_list")


class JurisdictionDeleteView(PlatformAdminRequiredMixin, View):
    """Suppression logique d'une juridiction."""

    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        item = get_object_or_404(Jurisdiction, pk=pk)
        try:
            delete_jurisdiction(actor=request.user, jurisdiction=item)  # type: ignore[arg-type]
        except PermissionDenied as exc:
            messages.error(request, str(exc))
            return redirect("tenants:jurisdiction_list")
        messages.success(request, _g("Juridiction supprimée."))
        return redirect("tenants:jurisdiction_list")
