"""Vues profil du compte connecté."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.urls import reverse
from django.utils.translation import gettext as _g
from django.views.generic import FormView, TemplateView

from apps.accounts.forms import ProfileForm
from apps.accounts.services import account_type_of, update_own_profile, user_memberships
from apps.core.mixins import BreadcrumbMixin


class ProfileDetailView(LoginRequiredMixin, BreadcrumbMixin, TemplateView):
    """Fiche profil du compte connecté."""

    template_name = "accounts/profile_detail.html"
    cabinet_required = False

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [{"label": _g("Mon profil")}]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx["profile_user"] = user
        ctx["memberships"] = user_memberships(user)  # type: ignore[arg-type]
        ctx["account_type"] = account_type_of(user)  # type: ignore[arg-type]
        return ctx


class ProfileUpdateView(LoginRequiredMixin, BreadcrumbMixin, FormView):
    """Modification du profil du compte connecté."""

    template_name = "accounts/profile_form.html"
    form_class = ProfileForm
    cabinet_required = False

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Mon profil"), "url": reverse("accounts:profile")},
            {"label": _g("Modifier")},
        ]

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_initial(self) -> dict[str, Any]:
        user = self.request.user
        return {
            "first_name": user.first_name,
            "last_name": user.last_name,
            "phone": user.phone,
        }

    def form_valid(self, form: ProfileForm) -> HttpResponse:
        data = form.cleaned_data
        password = (data.get("password") or "") or None
        try:
            update_own_profile(
                user=self.request.user,  # type: ignore[arg-type]
                first_name=str(data.get("first_name") or ""),
                last_name=str(data.get("last_name") or ""),
                phone=str(data.get("phone") or ""),
                password=str(password) if password else None,
            )
        except ValidationError as exc:
            if hasattr(exc, "message_dict"):
                for field, errs in exc.message_dict.items():
                    for err in errs:
                        form.add_error(field if field != "__all__" else None, err)
            else:
                form.add_error(None, exc)
            return self.form_invalid(form)

        if password:
            update_session_auth_hash(self.request, self.request.user)
        messages.success(self.request, _g("Profil mis à jour."))
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return reverse("accounts:profile")
