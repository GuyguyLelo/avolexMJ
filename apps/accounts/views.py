"""Vues d'authentification, inscription et invitations."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import FormView

from apps.accounts.forms import (
    AcceptInvitationForm,
    AvoLexPasswordResetForm,
    AvoLexSetPasswordForm,
    EmailAuthenticationForm,
    RegisterForm,
)
from apps.tenants.models import Invitation
from apps.tenants.services import (
    accept_invitation,
    list_user_cabinets,
    register_user_with_cabinet,
    set_session_cabinet,
)


class AvoLexLoginView(LoginView):
    """Connexion par e-mail."""

    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form: EmailAuthenticationForm) -> HttpResponse:
        """Connecte l'utilisateur et pose le cabinet courant en session."""
        response = super().form_valid(form)
        user = form.get_user()
        cabinets = list_user_cabinets(user)
        if cabinets:
            set_session_cabinet(self.request, cabinets[0])
        return response


class AvoLexLogoutView(LogoutView):
    """Déconnexion."""

    next_page = reverse_lazy("accounts:login")


class RegisterView(FormView):
    """Inscription d'un nouveau cabinet (owner)."""

    template_name = "accounts/register.html"
    form_class = RegisterForm
    success_url = reverse_lazy("core:home")

    def form_valid(self, form: RegisterForm) -> HttpResponse:
        """Crée user + cabinet et connecte l'utilisateur."""
        try:
            user, cabinet, _membership = register_user_with_cabinet(
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password1"],
                first_name=form.cleaned_data["first_name"],
                last_name=form.cleaned_data["last_name"],
                cabinet_name=form.cleaned_data["cabinet_name"],
            )
        except ValidationError as exc:
            if hasattr(exc, "message_dict"):
                for field, errors in exc.message_dict.items():
                    for error in errors:
                        form.add_error(field if field in form.fields else None, error)
            else:
                form.add_error(None, exc)
            return self.form_invalid(form)

        login(self.request, user, backend="django.contrib.auth.backends.ModelBackend")
        set_session_cabinet(self.request, cabinet)
        messages.success(self.request, _("Bienvenue sur AvoLex. Votre cabinet est prêt."))
        return redirect(self.get_success_url())


class AvoLexPasswordResetView(PasswordResetView):
    """Demande de réinitialisation du mot de passe."""

    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/email/password_reset_email.txt"
    subject_template_name = "accounts/email/password_reset_subject.txt"
    form_class = AvoLexPasswordResetForm
    success_url = reverse_lazy("accounts:password_reset_done")


class AvoLexPasswordResetDoneView(PasswordResetDoneView):
    """Confirmation d'envoi de l'e-mail de reset."""

    template_name = "accounts/password_reset_done.html"


class AvoLexPasswordResetConfirmView(PasswordResetConfirmView):
    """Saisie du nouveau mot de passe."""

    template_name = "accounts/password_reset_confirm.html"
    form_class = AvoLexSetPasswordForm
    success_url = reverse_lazy("accounts:password_reset_complete")


class AvoLexPasswordResetCompleteView(PasswordResetCompleteView):
    """Mot de passe réinitialisé."""

    template_name = "accounts/password_reset_complete.html"


class AcceptInvitationView(FormView):
    """Acceptation d'une invitation (création de compte ou rattachement)."""

    template_name = "accounts/accept_invitation.html"
    form_class = AcceptInvitationForm
    success_url = reverse_lazy("core:home")

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Charge l'invitation ou refuse si invalide."""
        self.invitation = (
            Invitation.objects.select_related("cabinet")
            .filter(token=kwargs["token"], is_deleted=False)
            .first()
        )
        if self.invitation is None or not self.invitation.is_pending:
            messages.error(request, _("Invitation invalide ou expirée."))
            return redirect("accounts:login")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Ajoute l'invitation au contexte."""
        ctx = super().get_context_data(**kwargs)
        ctx["invitation"] = self.invitation
        return ctx

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Si déjà connecté avec le bon e-mail, accepte sans formulaire password."""
        if request.user.is_authenticated:
            return self._accept_for_user(request.user)
        return super().get(request, *args, **kwargs)

    def form_valid(self, form: AcceptInvitationForm) -> HttpResponse:
        """Crée le compte et accepte l'invitation."""
        try:
            user, _membership, invitation = accept_invitation(
                token=self.invitation.token,
                user=None,
                password=form.cleaned_data["password1"],
                first_name=form.cleaned_data.get("first_name", ""),
                last_name=form.cleaned_data.get("last_name", ""),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)

        login(self.request, user, backend="django.contrib.auth.backends.ModelBackend")
        set_session_cabinet(self.request, invitation.cabinet)
        messages.success(self.request, _("Invitation acceptée. Bienvenue !"))
        return redirect(self.get_success_url())

    def _accept_for_user(self, user: Any) -> HttpResponse:
        """Accepte l'invitation pour un utilisateur déjà connecté."""
        try:
            _user, _membership, invitation = accept_invitation(
                token=self.invitation.token,
                user=user,
            )
        except ValidationError as exc:
            messages.error(self.request, str(exc.message if hasattr(exc, "message") else exc))
            return redirect("accounts:login")

        set_session_cabinet(self.request, invitation.cabinet)
        messages.success(self.request, _("Vous avez rejoint le cabinet."))
        return redirect(self.get_success_url())
