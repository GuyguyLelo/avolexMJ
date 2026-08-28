"""Formulaires procurations."""

from __future__ import annotations

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.procurations.models import Procuration
from apps.tenants.models import Cabinet


def _matter_label(matter: object) -> str:
    reference = getattr(matter, "reference", "")
    title = getattr(matter, "title", "")
    return f"{reference} — {title}".strip(" —")


class ProcurationForm(forms.ModelForm):
    """Le ministère délivre une procuration à un cabinet pour un dossier."""

    cabinet = forms.ModelChoiceField(
        label=_("Cabinet avocat"),
        queryset=Cabinet.objects.none(),
        required=False,
        empty_label=_("— Sélectionner un cabinet —"),
        widget=forms.Select(attrs={"class": "form-input", "data-procuration-cabinet": "1"}),
        help_text=_("Cabinet destinataire de la procuration."),
    )
    ministry_reference = forms.CharField(
        label=_("Référence ministérielle"),
        max_length=64,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
        help_text=_("Numéro porté sur l'acte du Ministère de la Justice."),
    )
    valid_from = forms.DateField(
        label=_("Valide à compter du"),
        required=False,
        widget=forms.DateInput(attrs={"class": "form-input", "type": "date"}),
    )
    expires_at = forms.DateField(
        label=_("Expire le"),
        required=False,
        widget=forms.DateInput(attrs={"class": "form-input", "type": "date"}),
    )

    class Meta:
        model = Procuration
        fields = ("matter", "reference", "purpose", "notes", "instrument")
        widgets = {
            "matter": forms.Select(attrs={"class": "form-input"}),
            "reference": forms.TextInput(
                attrs={
                    "class": "form-input",
                    "placeholder": _("Ex. PROC-2026-00012"),
                    "autocomplete": "off",
                }
            ),
            "purpose": forms.TextInput(
                attrs={
                    "class": "form-input",
                    "placeholder": _("Représentation du client et actes de procédure"),
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-input",
                    "rows": 3,
                    "placeholder": _("Contexte, précisions, observations du ministère…"),
                }
            ),
            "instrument": forms.ClearableFileInput(attrs={"class": "form-input"}),
        }

    def __init__(
        self,
        *args: object,
        matter_queryset: object = None,
        cabinet_queryset: object = None,
        include_cabinet: bool = False,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        if include_cabinet:
            self.fields["cabinet"].queryset = cabinet_queryset or Cabinet.objects.none()
            self.fields["cabinet"].required = True
        else:
            self.fields.pop("cabinet")
        self.fields["matter"].required = True
        self.fields["matter"].empty_label = _("— Sélectionner un dossier —")
        if matter_queryset is not None:
            self.fields["matter"].queryset = matter_queryset  # type: ignore[attr-defined]
        self.fields["matter"].label_from_instance = _matter_label  # type: ignore[method-assign]
        if self.instance and not self.instance._state.adding:
            self.fields["matter"].disabled = True
        if include_cabinet and not (matter_queryset and matter_queryset.exists()):  # type: ignore[union-attr]
            has_cabinet = bool(
                self.data.get("cabinet") if self.is_bound else self.initial.get("cabinet")
            )
            self.fields["matter"].help_text = (
                _("Aucun dossier ouvert pour ce cabinet.")
                if has_cabinet
                else _("Sélectionnez un cabinet pour afficher ses dossiers.")
            )
        else:
            self.fields["matter"].help_text = _(
                "Dossier déjà ouvert par le cabinet. La procuration l'autorise à y agir."
            )
        self.fields["purpose"].help_text = _(
            "Objet de la procuration (représentation, actes de procédure…)."
        )
        self.fields["reference"].required = False
        self.fields["reference"].label = _("Référence de la procuration")
        self.fields["reference"].help_text = _(
            "Numéro de la procuration. Laissez vide pour une attribution automatique "
            "(PROC-AAAA-NNNNN)."
        )

    def clean(self) -> dict[str, object]:
        cleaned = super().clean()
        cabinet = cleaned.get("cabinet")
        matter = cleaned.get("matter")
        if (
            cabinet
            and matter
            and getattr(matter, "cabinet_id", None) != getattr(cabinet, "pk", None)
        ):
            self.add_error(
                "matter",
                _("Ce dossier n'appartient pas au cabinet sélectionné."),
            )
        return cleaned

    def clean_purpose(self) -> str:
        purpose = (self.cleaned_data.get("purpose") or "").strip()
        if not purpose:
            raise forms.ValidationError(_("L'objet de la procuration est obligatoire."))
        return purpose

    def clean_reference(self) -> str:
        return (self.cleaned_data.get("reference") or "").strip()


class ProcurationGrantForm(forms.Form):
    """Octroi ministériel."""

    ministry_reference = forms.CharField(
        label=_("Référence ministérielle"),
        max_length=64,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    valid_from = forms.DateField(
        label=_("Valide à compter du"),
        required=False,
        widget=forms.DateInput(attrs={"class": "form-input", "type": "date"}),
    )
    expires_at = forms.DateField(
        label=_("Expire le"),
        required=False,
        widget=forms.DateInput(attrs={"class": "form-input", "type": "date"}),
    )
    notes = forms.CharField(
        label=_("Notes"),
        required=False,
        widget=forms.Textarea(attrs={"class": "form-input", "rows": 2}),
    )


class ProcurationDecisionForm(forms.Form):
    """Refus ou révocation — motif obligatoire."""

    reason = forms.CharField(
        label=_("Motif"),
        widget=forms.Textarea(attrs={"class": "form-input", "rows": 3}),
    )

    def clean_reason(self) -> str:
        reason = (self.cleaned_data.get("reason") or "").strip()
        if not reason:
            raise forms.ValidationError(_("Le motif est obligatoire."))
        return reason
