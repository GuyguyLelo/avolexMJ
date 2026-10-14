"""Vues CRUD du référentiel des entités étatiques RDC."""

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
from apps.tenants.forms import StateEntityForm
from apps.tenants.mixins import PlatformAdminRequiredMixin
from apps.tenants.models import StateEntity
from apps.tenants.services import (
    create_state_entity,
    delete_state_entity,
    state_entities_queryset,
    update_state_entity,
)
from apps.tenants.state_entities import ensure_default_state_entities


def _apply_form_errors(form: StateEntityForm, exc: ValidationError) -> None:
    if hasattr(exc, "message_dict"):
        for field, errs in exc.message_dict.items():
            for err in errs:
                form.add_error(field if field != "__all__" else None, err)
        return
    form.add_error(None, exc)


class StateEntityListView(PlatformAdminRequiredMixin, BreadcrumbMixin, ListView):
    """Référentiel des structures étatiques."""

    template_name = "tenants/state_entity_list.html"
    context_object_name = "state_entities"
    paginate_by = 25

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Paramètres")},
            {"label": _g("Données référentielles"), "url": reverse("core:settings")},
            {"label": _g("Entités étatiques")},
        ]

    def get_queryset(self) -> QuerySet[StateEntity]:
        ensure_default_state_entities()
        return state_entities_queryset(
            q=self.request.GET.get("q", ""),
            category=self.request.GET.get("category", ""),
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["filter_q"] = self.request.GET.get("q", "")
        ctx["filter_category"] = self.request.GET.get("category", "")
        categories = (
            StateEntity.objects.exclude(category="")
            .order_by("category")
            .values_list("category", flat=True)
            .distinct()
        )
        ctx["category_choices"] = [(c, c) for c in categories]
        return ctx


class StateEntityCreateView(PlatformAdminRequiredMixin, BreadcrumbMixin, FormView):
    """Création d'une entité étatique."""

    template_name = "tenants/state_entity_form.html"
    form_class = StateEntityForm

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Paramètres")},
            {"label": _g("Données référentielles"), "url": reverse("core:settings")},
            {"label": _g("Entités étatiques"), "url": reverse("tenants:state_entity_list")},
            {"label": _g("Nouvelle entité")},
        ]

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        initial.setdefault("is_active", True)
        return initial

    def form_valid(self, form: StateEntityForm) -> HttpResponse:
        data = form.cleaned_data
        try:
            create_state_entity(
                actor=self.request.user,  # type: ignore[arg-type]
                name=data["name"],
                category=data.get("category") or "",
                is_active=data.get("is_active", True),
            )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError):
                _apply_form_errors(form, exc)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Entité étatique créée."))
        return redirect("tenants:state_entity_list")


class StateEntityUpdateView(PlatformAdminRequiredMixin, BreadcrumbMixin, FormView):
    """Édition d'une entité étatique."""

    template_name = "tenants/state_entity_form.html"
    form_class = StateEntityForm

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.entity = get_object_or_404(StateEntity, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Paramètres")},
            {"label": _g("Données référentielles"), "url": reverse("core:settings")},
            {"label": _g("Entités étatiques"), "url": reverse("tenants:state_entity_list")},
            {"label": self.entity.name},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.entity
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["state_entity"] = self.entity
        return ctx

    def form_valid(self, form: StateEntityForm) -> HttpResponse:
        data = form.cleaned_data
        try:
            update_state_entity(
                actor=self.request.user,  # type: ignore[arg-type]
                entity=self.entity,
                name=data["name"],
                category=data.get("category") or "",
                is_active=data.get("is_active", True),
            )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError):
                _apply_form_errors(form, exc)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Entité étatique mise à jour."))
        return redirect("tenants:state_entity_list")


class StateEntityDeleteView(PlatformAdminRequiredMixin, View):
    """Suppression logique d'une entité étatique."""

    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        item = get_object_or_404(StateEntity, pk=pk)
        try:
            delete_state_entity(actor=request.user, entity=item)  # type: ignore[arg-type]
        except PermissionDenied as exc:
            messages.error(request, str(exc))
            return redirect("tenants:state_entity_list")
        messages.success(request, _g("Entité étatique supprimée."))
        return redirect("tenants:state_entity_list")
