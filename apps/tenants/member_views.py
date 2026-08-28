"""Vues CRUD des membres de cabinet."""

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
from apps.tenants.forms import MemberForm
from apps.tenants.mixins import CabinetRequiredMixin
from apps.tenants.models import Cabinet, Invitation, Membership
from apps.tenants.roles import PERM_INVITE
from apps.tenants.services import (
    add_cabinet_member,
    can_manage_members,
    memberships_queryset,
    remove_cabinet_member,
    require_manage_members,
    require_platform_admin,
    update_cabinet_member,
    user_has_cabinet_perm,
)


def _apply_form_errors(form: MemberForm, exc: ValidationError) -> None:
    if hasattr(exc, "message_dict"):
        for field, errs in exc.message_dict.items():
            for err in errs:
                form.add_error(field if field != "__all__" else None, err)
        return
    form.add_error(None, exc)


class TargetCabinetMixin(CabinetRequiredMixin):
    """Cabinet cible : URL de supervision, sinon cabinet de session."""

    cabinet_required = False

    def get_target_cabinet(self) -> Cabinet:
        request = self.request
        cabinet_pk = self.kwargs.get("cabinet_pk")
        if cabinet_pk:
            require_platform_admin(request.user)  # type: ignore[arg-type]
            return get_object_or_404(Cabinet, pk=cabinet_pk)
        cabinet = getattr(request, "cabinet", None)
        if cabinet is None:
            raise PermissionDenied(_g("Aucun cabinet sélectionné."))
        return cabinet  # type: ignore[no-any-return]

    def get_success_url(self) -> str:
        cabinet_pk = self.kwargs.get("cabinet_pk")
        if cabinet_pk:
            return reverse("tenants:cabinet_detail", args=[cabinet_pk])
        return reverse("tenants:member_list")


class MemberListView(TargetCabinetMixin, BreadcrumbMixin, ListView):
    """Équipe du cabinet courant (espace cabinet)."""

    template_name = "tenants/member_list.html"
    context_object_name = "memberships"
    paginate_by = 20
    cabinet_required = True

    def get_target_cabinet(self) -> Cabinet:
        cabinet = getattr(self.request, "cabinet", None)
        if cabinet is None:
            raise PermissionDenied(_g("Aucun cabinet sélectionné."))
        return cabinet  # type: ignore[no-any-return]

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [{"label": _g("Équipe")}]

    def get_queryset(self) -> QuerySet[Membership]:
        return memberships_queryset(cabinet=self.get_target_cabinet())

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        cabinet = self.get_target_cabinet()
        user = self.request.user  # type: ignore[assignment]
        ctx["team_cabinet"] = cabinet
        ctx["can_manage_members"] = can_manage_members(user=user, cabinet=cabinet)
        ctx["can_invite"] = user_has_cabinet_perm(user=user, cabinet=cabinet, perm=PERM_INVITE)
        ctx["invitations"] = (
            Invitation.objects.filter(cabinet=cabinet, accepted_at__isnull=True)
            .select_related("invited_by")
            .order_by("-created_at")[:10]
        )
        return ctx


class MemberCreateView(TargetCabinetMixin, BreadcrumbMixin, FormView):
    """Ajout d'un membre."""

    template_name = "tenants/member_form.html"
    form_class = MemberForm

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        cabinet = self.get_target_cabinet()
        require_manage_members(user=request.user, cabinet=cabinet)  # type: ignore[arg-type]
        self.team_cabinet = cabinet
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        cabinet_pk = self.kwargs.get("cabinet_pk")
        if cabinet_pk:
            return [
                {"label": _g("Cabinets avocats"), "url": reverse("tenants:cabinet_list")},
                {
                    "label": str(self.team_cabinet),
                    "url": reverse("tenants:cabinet_detail", args=[cabinet_pk]),
                },
                {"label": _g("Nouveau membre")},
            ]
        return [
            {"label": _g("Équipe"), "url": reverse("tenants:member_list")},
            {"label": _g("Nouveau membre")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["is_create"] = True
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["team_cabinet"] = self.team_cabinet
        ctx["is_create"] = True
        ctx["from_supervision"] = bool(self.kwargs.get("cabinet_pk"))
        return ctx

    def form_valid(self, form: MemberForm) -> HttpResponse:
        try:
            add_cabinet_member(
                actor=self.request.user,  # type: ignore[arg-type]
                cabinet=self.team_cabinet,
                email=form.cleaned_data["email"],
                role=form.cleaned_data["role"],
                first_name=form.cleaned_data.get("first_name") or "",
                last_name=form.cleaned_data.get("last_name") or "",
                phone=form.cleaned_data.get("phone") or "",
                password=form.cleaned_data.get("password") or None,
            )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError):
                _apply_form_errors(form, exc)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Membre ajouté."))
        return redirect(self.get_success_url())


class MemberUpdateView(TargetCabinetMixin, BreadcrumbMixin, FormView):
    """Modification d'un membre."""

    template_name = "tenants/member_form.html"
    form_class = MemberForm

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        cabinet = self.get_target_cabinet()
        require_manage_members(user=request.user, cabinet=cabinet)  # type: ignore[arg-type]
        self.team_cabinet = cabinet
        self.membership = get_object_or_404(
            Membership.objects.select_related("user", "cabinet"),
            pk=kwargs["pk"],
            cabinet=cabinet,
        )
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        cabinet_pk = self.kwargs.get("cabinet_pk")
        if cabinet_pk:
            return [
                {"label": _g("Cabinets avocats"), "url": reverse("tenants:cabinet_list")},
                {
                    "label": str(self.team_cabinet),
                    "url": reverse("tenants:cabinet_detail", args=[cabinet_pk]),
                },
                {"label": _g("Modifier le membre")},
            ]
        return [
            {"label": _g("Équipe"), "url": reverse("tenants:member_list")},
            {"label": _g("Modifier le membre")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["is_create"] = False
        if not self.request.POST:
            user = self.membership.user
            kwargs["initial"] = {
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "phone": user.phone,
                "role": self.membership.role,
                "is_active": self.membership.is_active,
            }
        return kwargs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["team_cabinet"] = self.team_cabinet
        ctx["membership"] = self.membership
        ctx["is_create"] = False
        ctx["from_supervision"] = bool(self.kwargs.get("cabinet_pk"))
        return ctx

    def form_valid(self, form: MemberForm) -> HttpResponse:
        try:
            update_cabinet_member(
                actor=self.request.user,  # type: ignore[arg-type]
                membership=self.membership,
                role=form.cleaned_data["role"],
                is_active=form.cleaned_data.get("is_active", True),
                first_name=form.cleaned_data.get("first_name") or "",
                last_name=form.cleaned_data.get("last_name") or "",
                phone=form.cleaned_data.get("phone") or "",
            )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError):
                _apply_form_errors(form, exc)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Membre mis à jour."))
        return redirect(self.get_success_url())


class MemberDeleteView(TargetCabinetMixin, View):
    """Retrait d'un membre."""

    http_method_names = ("post",)

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        cabinet = self.get_target_cabinet()
        membership = get_object_or_404(Membership, pk=kwargs["pk"], cabinet=cabinet)
        try:
            remove_cabinet_member(actor=request.user, membership=membership)  # type: ignore[arg-type]
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            if self.kwargs.get("cabinet_pk"):
                return redirect("tenants:cabinet_detail", pk=cabinet.pk)
            return redirect("tenants:member_list")
        messages.success(request, _g("Membre retiré."))
        return redirect(self.get_success_url())


__all__ = [
    "MemberCreateView",
    "MemberDeleteView",
    "MemberListView",
    "MemberUpdateView",
]
