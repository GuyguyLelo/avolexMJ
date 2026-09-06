"""Formulaires d'authentification et d'inscription."""

from __future__ import annotations

from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User


class EmailAuthenticationForm(AuthenticationForm):
    """Connexion par e-mail."""

    username = forms.EmailField(
        label=_("Adresse e-mail"),
        widget=forms.EmailInput(
            attrs={
                "autocomplete": "email",
                "autofocus": True,
                "class": "form-input",
                "placeholder": "exemple@email.com",
            }
        ),
    )
    password = forms.CharField(
        label=_("Mot de passe"),
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "current-password",
                "class": "form-input",
                "placeholder": "••••••••",
            }
        ),
    )

    error_messages = {
        "invalid_login": _("E-mail ou mot de passe incorrect."),
        "inactive": _("Ce compte est désactivé."),
    }

    def clean(self) -> dict[str, object]:
        """Authentifie via e-mail (USERNAME_FIELD)."""
        email = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")
        if email and password:
            self.user_cache = authenticate(
                self.request,
                username=email,
                password=password,
            )
            if self.user_cache is None:
                raise ValidationError(
                    self.error_messages["invalid_login"],
                    code="invalid_login",
                )
            self.confirm_login_allowed(self.user_cache)
        return self.cleaned_data


class RegisterForm(forms.Form):
    """Inscription : compte + premier cabinet."""

    first_name = forms.CharField(
        label=_("Prénom"),
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-input", "autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        label=_("Nom"),
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-input", "autocomplete": "family-name"}),
    )
    email = forms.EmailField(
        label=_("Adresse e-mail"),
        widget=forms.EmailInput(attrs={"class": "form-input", "autocomplete": "email"}),
    )
    password1 = forms.CharField(
        label=_("Mot de passe"),
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-input", "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label=_("Confirmation du mot de passe"),
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-input", "autocomplete": "new-password"}),
    )
    cabinet_name = forms.CharField(
        label=_("Nom du cabinet"),
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )

    def clean_email(self) -> str:
        """Normalise et vérifie l'unicité de l'e-mail."""
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError(_("Un compte existe déjà avec cet e-mail."))
        return email

    def clean(self) -> dict[str, object]:
        """Vérifie la concordance et la politique de mots de passe."""
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", _("Les mots de passe ne correspondent pas."))
        elif p1:
            try:
                password_validation.validate_password(str(p1))
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned


class AcceptInvitationForm(forms.Form):
    """Acceptation d'invitation pour un nouvel utilisateur."""

    first_name = forms.CharField(
        label=_("Prénom"),
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    last_name = forms.CharField(
        label=_("Nom"),
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    password1 = forms.CharField(
        label=_("Mot de passe"),
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-input", "autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label=_("Confirmation"),
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-input", "autocomplete": "new-password"}),
    )

    def clean(self) -> dict[str, object]:
        """Vérifie la concordance des mots de passe."""
        cleaned = super().clean()
        if cleaned.get("password1") != cleaned.get("password2"):
            self.add_error("password2", _("Les mots de passe ne correspondent pas."))
        return cleaned


class AvoLexPasswordResetForm(PasswordResetForm):
    """Reset password avec widget cohérent."""

    email = forms.EmailField(
        label=_("Adresse e-mail"),
        widget=forms.EmailInput(attrs={"class": "form-input", "autocomplete": "email"}),
    )


class AvoLexSetPasswordForm(SetPasswordForm):
    """Définition d'un nouveau mot de passe."""

    new_password1 = forms.CharField(
        label=_("Nouveau mot de passe"),
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-input", "autocomplete": "new-password"}),
    )
    new_password2 = forms.CharField(
        label=_("Confirmation"),
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "form-input", "autocomplete": "new-password"}),
    )
