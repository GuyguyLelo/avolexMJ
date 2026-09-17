"""Formulaires tenants."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core.bar_associations import bar_association_choices_with_value
from apps.core.widgets import PrivateClearableFileInput
from apps.tenants.models import Cabinet, LegalPracticeArea
from apps.tenants.roles import Role
from apps.tenants.services import validate_cabinet_contract_file

_INPUT = {"class": "form-input"}
_CONTRACT_ACCEPT = (
    ".pdf,.doc,.docx,.jpg,.jpeg,.png,.webp,"
    "application/pdf,application/msword,"
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
    "image/jpeg,image/png,image/webp"
)


class InviteMemberForm(forms.Form):
    """Invitation d'un collaborateur."""

    email = forms.EmailField(
        label=_("E-mail du collaborateur"),
        widget=forms.EmailInput(attrs={"class": "form-input", "autocomplete": "email"}),
    )
    role = forms.ChoiceField(
        label=_("Rôle"),
        choices=Role.choices,
        widget=forms.Select(attrs={"class": "form-input"}),
    )


class CabinetForm(forms.ModelForm):
    """Création / édition d'un cabinet (supervision plateforme)."""

    class Meta:
        model = Cabinet
        fields = (
            "name",
            "contract_number",
            "contract_file",
            "legal_name",
            "siret",
            "vat_number",
            "bar_association",
            "address_line1",
            "is_active",
        )
        widgets = {
            "name": forms.TextInput(attrs=_INPUT),
            "contract_number": forms.TextInput(attrs={**_INPUT, "autocomplete": "off"}),
            "legal_name": forms.TextInput(attrs=_INPUT),
            "siret": forms.TextInput(attrs=_INPUT),
            "vat_number": forms.TextInput(attrs=_INPUT),
            "address_line1": forms.TextInput(attrs=_INPUT),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check"}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[misc]
        current = ""
        if self.instance.pk:
            current = self.instance.bar_association or ""
        elif self.initial.get("bar_association"):
            current = str(self.initial["bar_association"])
        self.fields["bar_association"] = forms.ChoiceField(
            label=_("Barreau"),
            required=False,
            choices=bar_association_choices_with_value(current),
            widget=forms.Select(attrs=_INPUT),
        )
        contract_widget = PrivateClearableFileInput(
            attrs={"class": "form-input", "accept": _CONTRACT_ACCEPT},
        )
        self.fields["contract_file"].required = False
        self.fields["contract_file"].widget = contract_widget
        self.fields["contract_file"].help_text = _("PDF, DOC, DOCX ou image.")

    def clean_contract_file(self) -> object:
        uploaded = self.cleaned_data.get("contract_file")
        if uploaded is False or not uploaded:
            return uploaded
        validate_cabinet_contract_file(uploaded)
        return uploaded


class MemberForm(forms.Form):
    """Ajout / édition d'un membre de cabinet."""

    email = forms.EmailField(
        label=_("E-mail"),
        widget=forms.EmailInput(attrs={"class": "form-input", "autocomplete": "email"}),
    )
    first_name = forms.CharField(
        label=_("Prénom"),
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        label=_("Nom"),
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "autocomplete": "family-name"}),
    )
    phone = forms.CharField(
        label=_("Téléphone"),
        max_length=32,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "autocomplete": "tel"}),
    )
    role = forms.ChoiceField(
        label=_("Rôle"),
        choices=Role.choices,
        widget=forms.Select(attrs={"class": "form-input"}),
    )
    password = forms.CharField(
        label=_("Mot de passe"),
        required=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-input", "autocomplete": "new-password"},
            render_value=False,
        ),
        help_text=_(
            "Facultatif à la création. Sans mot de passe, le compte ne pourra pas "
            "se connecter tant qu'il n'en aura pas défini un."
        ),
    )
    is_active = forms.BooleanField(
        label=_("Membre actif"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={"class": "form-check"}),
    )

    def __init__(
        self,
        *args: object,
        is_create: bool = True,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[misc]
        if not is_create:
            self.fields["email"].disabled = True
            self.fields["email"].required = False
            self.fields.pop("password")
        else:
            self.fields.pop("is_active")


class PracticeAreaForm(forms.ModelForm):
    """Création / édition d'une matière du référentiel."""

    class Meta:
        model = LegalPracticeArea
        fields = ("name", "description", "is_active")
        widgets = {
            "name": forms.TextInput(attrs=_INPUT),
            "description": forms.Textarea(attrs={**_INPUT, "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check"}),
        }


class CabinetSpecialtyForm(forms.Form):
    """Ajout d'une spécialité à un cabinet."""

    practice_area = forms.ModelChoiceField(
        label=_("Matière juridique"),
        queryset=LegalPracticeArea.objects.none(),
        widget=forms.Select(attrs={"class": "form-input"}),
        empty_label=_("— Choisir une matière —"),
    )

    def __init__(self, *args: object, queryset=None, **kwargs: object) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)  # type: ignore[misc]
        if queryset is not None:
            self.fields["practice_area"].queryset = queryset


class CabinetCreateForm(CabinetForm):
    """Création d'un cabinet avec le compte propriétaire."""

    class Meta(CabinetForm.Meta):
        fields = tuple(f for f in CabinetForm.Meta.fields if f != "is_active")

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[misc]
        self.fields["contract_number"].required = True

    owner_email = forms.EmailField(
        label=_("E-mail du Caïman"),
        widget=forms.EmailInput(attrs={"class": "form-input", "autocomplete": "email"}),
    )
    owner_first_name = forms.CharField(
        label=_("Prénom"),
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "autocomplete": "given-name"}),
    )
    owner_last_name = forms.CharField(
        label=_("Nom"),
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input", "autocomplete": "family-name"}),
    )
