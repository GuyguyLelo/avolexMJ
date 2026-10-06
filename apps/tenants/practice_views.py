"""Vues CRUD matières juridiques et spécialités de cabinet."""

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
from apps.tenants.forms import CabinetSpecialtyForm, PracticeAreaForm
from apps.tenants.legal_areas import ensure_default_legal_practice_areas
from apps.tenants.member_views import TargetCabinetMixin
from apps.tenants.mixins import PlatformAdminRequiredMixin
from apps.tenants.models import Cabinet, CabinetPracticeArea, LegalPracticeArea
from apps.tenants.services import (
    add_cabinet_practice_area,
    cabinet_practice_areas_queryset,
    can_manage_cabinet,
    create_legal_practice_area,
    delete_legal_practice_area,
    legal_practice_areas_queryset,
    remove_cabinet_practice_area,
    require_manage_cabinet_settings,
    update_legal_practice_area,
)


def _available_practice_areas(cabinet: Cabinet) -> QuerySet[LegalPracticeArea]:
    taken = cabinet_practice_areas_queryset(cabinet=cabinet).values("practice_area_id")
    return LegalPracticeArea.objects.filter(is_active=True).exclude(pk__in=taken).order_by("name")


def _apply_form_errors(form: PracticeAreaForm, exc: ValidationError) -> None:
    if hasattr(exc, "message_dict"):
        for field, errs in exc.message_dict.items():
            for err in errs:
                form.add_error(field if field != "__all__" else None, err)
        return
    form.add_error(None, exc)


class PracticeAreaListView(PlatformAdminRequiredMixin, BreadcrumbMixin, ListView):
    """Référentiel national des matières juridiques."""

    template_name = "tenants/practice_area_list.html"
    context_object_name = "practice_areas"
    paginate_by = 20

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Paramètres")},
            {"label": _g("Données référentielles"), "url": reverse("core:settings")},
            {"label": _g("Matières juridiques")},
        ]

    def get_queryset(self) -> QuerySet[LegalPracticeArea]:
        ensure_default_legal_practice_areas()
        return legal_practice_areas_queryset(q=self.request.GET.get("q", ""))

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["filter_q"] = self.request.GET.get("q", "")
        return ctx


class PracticeAreaCreateView(PlatformAdminRequiredMixin, BreadcrumbMixin, FormView):
    """Création d'une matière du référentiel."""

    template_name = "tenants/practice_area_form.html"
    form_class = PracticeAreaForm

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Paramètres")},
            {"label": _g("Données référentielles"), "url": reverse("core:settings")},
            {"label": _g("Matières juridiques"), "url": reverse("tenants:practice_area_list")},
            {"label": _g("Nouvelle matière")},
        ]

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        initial.setdefault("is_active", True)
        return initial

    def form_valid(self, form: PracticeAreaForm) -> HttpResponse:
        data = form.cleaned_data
        try:
            create_legal_practice_area(
                actor=self.request.user,  # type: ignore[arg-type]
                name=data["name"],
                description=data.get("description") or "",
                is_active=data.get("is_active", True),
            )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError):
                _apply_form_errors(form, exc)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Matière juridique créée."))
        return redirect("tenants:practice_area_list")


class PracticeAreaUpdateView(PlatformAdminRequiredMixin, BreadcrumbMixin, FormView):
    """Édition d'une matière du référentiel."""

    template_name = "tenants/practice_area_form.html"
    form_class = PracticeAreaForm

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.area = get_object_or_404(LegalPracticeArea, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Paramètres")},
            {"label": _g("Données référentielles"), "url": reverse("core:settings")},
            {"label": _g("Matières juridiques"), "url": reverse("tenants:practice_area_list")},
            {"label": self.area.name},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.area
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["practice_area"] = self.area
        return ctx

    def form_valid(self, form: PracticeAreaForm) -> HttpResponse:
        data = form.cleaned_data
        try:
            update_legal_practice_area(
                actor=self.request.user,  # type: ignore[arg-type]
                area=self.area,
                name=data["name"],
                description=data.get("description") or "",
                is_active=data.get("is_active", True),
            )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError):
                _apply_form_errors(form, exc)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Matière juridique mise à jour."))
        return redirect("tenants:practice_area_list")


class PracticeAreaDeleteView(PlatformAdminRequiredMixin, View):
    """Suppression logique d'une matière."""

    http_method_names = ("post",)

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        area = get_object_or_404(LegalPracticeArea, pk=pk)
        try:
            delete_legal_practice_area(actor=request.user, area=area)  # type: ignore[arg-type]
        except PermissionDenied as exc:
            messages.error(request, str(exc))
            return redirect("tenants:practice_area_list")
        messages.success(request, _g("Matière juridique supprimée."))
        return redirect("tenants:practice_area_list")


class CabinetSpecialtyListView(TargetCabinetMixin, BreadcrumbMixin, FormView):
    """Spécialités du cabinet courant."""

    template_name = "tenants/specialty_list.html"
    form_class = CabinetSpecialtyForm
    cabinet_required = True

    def get_target_cabinet(self) -> Cabinet:
        cabinet = getattr(self.request, "cabinet", None)
        if cabinet is None:
            raise PermissionDenied(_g("Aucun cabinet sélectionné."))
        return cabinet  # type: ignore[no-any-return]

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Paramètres")},
            {"label": _g("Données référentielles"), "url": reverse("core:settings")},
            {"label": _g("Spécialités")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        ensure_default_legal_practice_areas()
        kwargs["queryset"] = _available_practice_areas(self.get_target_cabinet())
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        cabinet = self.get_target_cabinet()
        ctx["team_cabinet"] = cabinet
        ctx["links"] = cabinet_practice_areas_queryset(cabinet=cabinet)
        ctx["can_manage_specialties"] = can_manage_cabinet(
            user=self.request.user,  # type: ignore[arg-type]
            cabinet=cabinet,
        )
        return ctx

    def form_valid(self, form: CabinetSpecialtyForm) -> HttpResponse:
        cabinet = self.get_target_cabinet()
        try:
            require_manage_cabinet_settings(user=self.request.user, cabinet=cabinet)  # type: ignore[arg-type]
            add_cabinet_practice_area(
                actor=self.request.user,  # type: ignore[arg-type]
                cabinet=cabinet,
                practice_area=form.cleaned_data["practice_area"],
            )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError):
                form.add_error(None, exc)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Spécialité ajoutée."))
        return redirect("tenants:specialty_list")


class CabinetSpecialtyAddView(TargetCabinetMixin, View):
    """Ajout POST d'une spécialité (fiche cabinet ou page spécialités)."""

    http_method_names = ("post",)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        cabinet = self.get_target_cabinet()
        form = CabinetSpecialtyForm(
            request.POST,
            queryset=_available_practice_areas(cabinet),
        )
        if not form.is_valid():
            messages.error(request, _g("Choisissez une matière juridique."))
        else:
            try:
                add_cabinet_practice_area(
                    actor=request.user,  # type: ignore[arg-type]
                    cabinet=cabinet,
                    practice_area=form.cleaned_data["practice_area"],
                )
                messages.success(request, _g("Spécialité ajoutée."))
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, str(exc))
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        if self.kwargs.get("cabinet_pk"):
            return reverse("tenants:cabinet_detail", args=[self.kwargs["cabinet_pk"]])
        return reverse("tenants:specialty_list")


class CabinetSpecialtyRemoveView(TargetCabinetMixin, View):
    """Retrait d'une spécialité."""

    http_method_names = ("post",)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        cabinet = self.get_target_cabinet()
        link = get_object_or_404(CabinetPracticeArea, pk=kwargs["pk"], cabinet=cabinet)
        try:
            remove_cabinet_practice_area(actor=request.user, link=link)  # type: ignore[arg-type]
            messages.success(request, _g("Spécialité retirée."))
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
        if self.kwargs.get("cabinet_pk"):
            return redirect("tenants:cabinet_detail", pk=cabinet.pk)
        return redirect("tenants:specialty_list")
