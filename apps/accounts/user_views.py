"""Vues de gestion des utilisateurs (SuperAdmin)."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _g
from django.views import View
from django.views.generic import DetailView, FormView, ListView

from apps.accounts.forms import PlatformUserForm
from apps.accounts.services import (
    ACCOUNT_CABINET,
    account_type_of,
    create_user_as_platform_admin,
    deactivate_user_as_platform_admin,
    update_user_as_platform_admin,
    user_memberships,
    users_queryset,
)
from apps.core.mixins import BreadcrumbMixin
from apps.tenants.mixins import SuperAdminRequiredMixin

User = get_user_model()


def _apply_form_errors(form: PlatformUserForm, exc: ValidationError) -> None:
    if hasattr(exc, "message_dict"):
        for field, errs in exc.message_dict.items():
            for err in errs:
                form.add_error(field if field != "__all__" else None, err)
        return
    form.add_error(None, exc)


class UserListView(SuperAdminRequiredMixin, BreadcrumbMixin, ListView):
    """Annuaire des comptes AvoLex."""

    template_name = "accounts/user_list.html"
    context_object_name = "users"
    paginate_by = 25
    cabinet_required = False

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [{"label": _g("Utilisateurs")}]

    def get_queryset(self) -> QuerySet:
        return users_queryset(
            q=self.request.GET.get("q") or "",
            status=self.request.GET.get("status") or "",
            role=self.request.GET.get("role") or "",
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["filter_q"] = self.request.GET.get("q") or ""
        ctx["filter_status"] = self.request.GET.get("status") or ""
        ctx["filter_role"] = self.request.GET.get("role") or ""
        return ctx


class UserCreateView(SuperAdminRequiredMixin, BreadcrumbMixin, FormView):
    """Création d'un compte."""

    template_name = "accounts/user_form.html"
    form_class = PlatformUserForm
    cabinet_required = False

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Utilisateurs"), "url": reverse("accounts:user_list")},
            {"label": _g("Nouveau")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["is_create"] = True
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["is_create"] = True
        return ctx

    def form_valid(self, form: PlatformUserForm) -> HttpResponse:
        data = form.cleaned_data
        try:
            user = create_user_as_platform_admin(
                actor=self.request.user,  # type: ignore[arg-type]
                email=data["email"],
                password=data["password"],
                first_name=data.get("first_name") or "",
                last_name=data.get("last_name") or "",
                phone=data.get("phone") or "",
                account_type=data.get("account_type") or ACCOUNT_CABINET,
                is_active=bool(data.get("is_active")),
                cabinet=data.get("cabinet"),
                cabinet_role=data.get("cabinet_role") or None,
            )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError):
                _apply_form_errors(form, exc)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Utilisateur créé."))
        return redirect("accounts:user_detail", pk=user.pk)


class UserDetailView(SuperAdminRequiredMixin, BreadcrumbMixin, DetailView):
    """Fiche utilisateur."""

    template_name = "accounts/user_detail.html"
    context_object_name = "account_user"
    model = User
    cabinet_required = False

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Utilisateurs"), "url": reverse("accounts:user_list")},
            {"label": str(self.object)},
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["memberships"] = user_memberships(self.object)
        ctx["account_type"] = account_type_of(self.object)
        return ctx


class UserUpdateView(SuperAdminRequiredMixin, BreadcrumbMixin, FormView):
    """Édition d'un compte."""

    template_name = "accounts/user_form.html"
    form_class = PlatformUserForm
    cabinet_required = False

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        self.account_user = get_object_or_404(User, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Utilisateurs"), "url": reverse("accounts:user_list")},
            {
                "label": str(self.account_user),
                "url": reverse("accounts:user_detail", args=[self.account_user.pk]),
            },
            {"label": _g("Modifier")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["is_create"] = False
        if not kwargs.get("data"):
            kwargs["initial"] = {
                "email": self.account_user.email,
                "first_name": self.account_user.first_name,
                "last_name": self.account_user.last_name,
                "phone": self.account_user.phone,
                "account_type": account_type_of(self.account_user),
                "is_active": self.account_user.is_active,
            }
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["is_create"] = False
        ctx["account_user"] = self.account_user
        return ctx

    def form_valid(self, form: PlatformUserForm) -> HttpResponse:
        data = form.cleaned_data
        try:
            update_user_as_platform_admin(
                actor=self.request.user,  # type: ignore[arg-type]
                user=self.account_user,
                email=data["email"],
                first_name=data.get("first_name") or "",
                last_name=data.get("last_name") or "",
                phone=data.get("phone") or "",
                password=data.get("password") or None,
                account_type=data.get("account_type") or ACCOUNT_CABINET,
                is_active=bool(data.get("is_active")),
            )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError):
                _apply_form_errors(form, exc)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Utilisateur mis à jour."))
        return redirect("accounts:user_detail", pk=self.account_user.pk)


class UserDeactivateView(SuperAdminRequiredMixin, View):
    """Désactivation d'un compte."""

    http_method_names = ("post",)
    cabinet_required = False

    def post(self, request: HttpRequest, pk: str) -> HttpResponse:
        user = get_object_or_404(User, pk=pk)
        try:
            deactivate_user_as_platform_admin(actor=request.user, user=user)  # type: ignore[arg-type]
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect("accounts:user_detail", pk=pk)
        messages.success(request, _g("Utilisateur désactivé."))
        return redirect("accounts:user_list")
