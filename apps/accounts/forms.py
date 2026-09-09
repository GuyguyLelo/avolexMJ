"""Formulaires d'authentification et d'inscription."""

from __future__ import annotations

from django import forms
from django.contrib.auth import authenticate, password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import User
from apps.tenants.models import Cabinet
from apps.tenants.roles import Role


class EmailAuthenticationForm(AuthenticationForm):
    """Connexion par nom d'utilisateur (e-mail du compte)."""

    username = forms.CharField(
        label=_("Nom utilisateur"),
        widget=forms.TextInput(
            attrs={
                "autocomplete": "username",
                "autofocus": True,
                "class": "form-input",
                "placeholder": _("Nom utilisateur"),
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
        "invalid_login": _("Nom d'utilisateur ou mot de passe incorrect."),
        "inactive": _("Ce compte est désactivé."),
    }

    def clean(self) -> dict[str, object]:
        """Authentifie via l'identifiant (e-mail ou nom, insensible à la casse)."""
        from apps.accounts.models import User

        username = (self.cleaned_data.get("username") or "").strip()
        password = self.cleaned_data.get("password")
        if username and password:
            matched = User.objects.filter(email__iexact=username).first()
            auth_username = matched.email if matched is not None else username
            self.user_cache = authenticate(
                self.request,
                username=auth_username,
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


_INPUT = {"class": "form-input"}


class ProfileForm(forms.Form):
    """Édition du profil du compte connecté."""

    first_name = forms.CharField(
        label=_("Prénom"),
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={**_INPUT, "autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        label=_("Nom"),
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={**_INPUT, "autocomplete": "family-name"}),
    )
    phone = forms.CharField(
        label=_("Téléphone"),
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={**_INPUT, "autocomplete": "tel"}),
    )
    current_password = forms.CharField(
        label=_("Mot de passe actuel"),
        required=False,
        strip=False,
        widget=forms.PasswordInput(
            attrs={**_INPUT, "autocomplete": "current-password"},
            render_value=False,
        ),
        help_text=_("Requis uniquement pour changer le mot de passe."),
    )
    password = forms.CharField(
        label=_("Nouveau mot de passe"),
        required=False,
        strip=False,
        widget=forms.PasswordInput(
            attrs={**_INPUT, "autocomplete": "new-password"},
            render_value=False,
        ),
        help_text=_("Laisser vide pour conserver le mot de passe actuel."),
    )
    password_confirm = forms.CharField(
        label=_("Confirmation du nouveau mot de passe"),
        required=False,
        strip=False,
        widget=forms.PasswordInput(
            attrs={**_INPUT, "autocomplete": "new-password"},
            render_value=False,
        ),
    )

    def __init__(self, *args: object, user: User | None = None, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[misc]
        self.user = user

    def clean(self) -> dict[str, object]:
        cleaned = super().clean()
        password = cleaned.get("password") or ""
        confirm = cleaned.get("password_confirm") or ""
        current = cleaned.get("current_password") or ""
        if password or confirm or current:
            if not password:
                self.add_error("password", _("Indiquez le nouveau mot de passe."))
            elif password != confirm:
                self.add_error("password_confirm", _("Les mots de passe ne correspondent pas."))
            else:
                try:
                    password_validation.validate_password(str(password), user=self.user)
                except ValidationError as exc:
                    self.add_error("password", exc)
            if self.user is None or not self.user.check_password(str(current)):
                self.add_error("current_password", _("Mot de passe actuel incorrect."))
        return cleaned


class PlatformUserForm(forms.Form):
    """Création / édition d'un utilisateur (supervision plateforme)."""

    email = forms.CharField(
        label=_("Identifiant"),
        max_length=254,
        widget=forms.TextInput(attrs={**_INPUT, "autocomplete": "username"}),
    )
    first_name = forms.CharField(
        label=_("Prénom"),
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={**_INPUT, "autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        label=_("Nom"),
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={**_INPUT, "autocomplete": "family-name"}),
    )
    phone = forms.CharField(
        label=_("Téléphone"),
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={**_INPUT, "autocomplete": "tel"}),
    )
    password = forms.CharField(
        label=_("Mot de passe"),
        required=False,
        strip=False,
        widget=forms.PasswordInput(
            attrs={**_INPUT, "autocomplete": "new-password"},
            render_value=False,
        ),
    )
    password_confirm = forms.CharField(
        label=_("Confirmation du mot de passe"),
        required=False,
        strip=False,
        widget=forms.PasswordInput(
            attrs={**_INPUT, "autocomplete": "new-password"},
            render_value=False,
        ),
    )
    account_type = forms.ChoiceField(
        label=_("Type de compte"),
        choices=(),
        widget=forms.Select(attrs={**_INPUT, "id": "id_account_type"}),
        help_text=_(
            "SuperAdmin et Administrateur : comptes ministère, non liés à un cabinet d'avocats. "
            "Compte cabinet : rattachement obligatoire à un cabinet d'avocats."
        ),
    )
    cabinet = forms.ModelChoiceField(
        label=_("Cabinet d'avocats"),
        queryset=Cabinet.objects.none(),
        required=False,
        empty_label=_("— Sélectionner un cabinet —"),
        widget=forms.Select(attrs={**_INPUT, "id": "id_cabinet"}),
        help_text=_("Obligatoire pour un compte cabinet."),
    )
    cabinet_role = forms.ChoiceField(
        label=_("Rôle dans le cabinet"),
        choices=Role.choices,
        required=False,
        initial=Role.LAWYER,
        widget=forms.Select(attrs={**_INPUT, "id": "id_cabinet_role"}),
    )
    is_active = forms.BooleanField(
        label=_("Compte actif"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check"}),
    )

    def __init__(self, *args: object, is_create: bool = True, **kwargs: object) -> None:
        from apps.accounts.services import ACCOUNT_CABINET, ACCOUNT_TYPE_CHOICES

        super().__init__(*args, **kwargs)  # type: ignore[misc]
        self.is_create = is_create
        self.fields["account_type"].choices = ACCOUNT_TYPE_CHOICES
        self.fields["cabinet"].queryset = Cabinet.objects.filter(is_active=True).order_by("name")
        if is_create:
            self.fields["password"].required = True
            self.fields["password_confirm"].required = True
            self.fields["password"].help_text = _("Obligatoire à la création.")
            self.fields["account_type"].initial = ACCOUNT_CABINET
        else:
            self.fields["password"].help_text = _(
                "Laisser vide pour conserver le mot de passe actuel."
            )
            # En édition : rattachement géré via la fiche / équipe cabinet.
            self.fields["cabinet"].widget = forms.HiddenInput()
            self.fields["cabinet_role"].widget = forms.HiddenInput()

    def clean(self) -> dict[str, object]:
        from apps.accounts.services import ACCOUNT_CABINET

        cleaned = super().clean()
        password = cleaned.get("password") or ""
        confirm = cleaned.get("password_confirm") or ""
        if self.is_create or password or confirm:
            if not password:
                self.add_error("password", _("Le mot de passe est obligatoire."))
            elif password != confirm:
                self.add_error("password_confirm", _("Les mots de passe ne correspondent pas."))
            elif password:
                try:
                    password_validation.validate_password(str(password))
                except ValidationError as exc:
                    self.add_error("password", exc)

        account_type = cleaned.get("account_type") or ACCOUNT_CABINET
        if self.is_create and account_type == ACCOUNT_CABINET and not cleaned.get("cabinet"):
            self.add_error(
                "cabinet",
                _("Le cabinet d'avocats est obligatoire pour un compte cabinet."),
            )
        return cleaned
