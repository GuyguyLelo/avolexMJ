"""Formulaires dossiers."""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _
from django.forms import formset_factory

from apps.core.kinshasa_courts import court_choices_with_value
from apps.matters.models import Matter, MatterParty, MatterScale, MatterStatus
from apps.matters.services import validate_matter_scale
from apps.tenants.legal_areas import ensure_default_legal_practice_areas
from apps.tenants.models import Cabinet, LegalPracticeArea

User = get_user_model()


class MatterPartyForm(forms.ModelForm):
    """Formulaire pour une partie d'un dossier."""

    class Meta:
        model = MatterParty
        fields = ("name", "role", "is_state_entity", "notes")
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input"}),
            "role": forms.Select(attrs={"class": "form-input"}),
            "is_state_entity": forms.CheckboxInput(attrs={"class": "form-input"}),
            "notes": forms.Textarea(attrs={"class": "form-input", "rows": 2}),
        }


MatterPartyFormSet = formset_factory(MatterPartyForm, extra=2, can_delete=False)


class MatterForm(forms.ModelForm):
    """Création / édition d'un dossier."""

    jurisdiction = forms.ChoiceField(
        label=_("Juridiction"),
        required=True,
        choices=[],
        widget=forms.Select(attrs={"class": "form-input"}),
        help_text=_("Tribunal ou juridiction saisie pour ce dossier."),
    )

    class Meta:
        model = Matter
        fields = (
            "title",
            "scale",
            "jurisdiction",
            "description",
            "practice_area",
            "status",
            "opened_at",
            "closed_at",
            "initial_pdf",
            "notes",
        )
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-input"}),
            "scale": forms.Select(attrs={"class": "form-input"}),
            "description": forms.Textarea(attrs={"class": "form-input", "rows": 4}),
            "practice_area": forms.Select(attrs={"class": "form-input"}),
            "status": forms.Select(attrs={"class": "form-input"}),
            "opened_at": forms.DateInput(attrs={"class": "form-input", "type": "date"}),
            "closed_at": forms.DateInput(attrs={"class": "form-input", "type": "date"}),
            "initial_pdf": forms.FileInput(attrs={"class": "form-input", "accept": ".pdf,application/pdf"}),
            "notes": forms.Textarea(attrs={"class": "form-input", "rows": 3}),
        }

    def __init__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = MatterStatus.choices
        self.fields["scale"].choices = MatterScale.choices
        self.fields["scale"].help_text = _(
            "Le Ministère de la Justice traite le dossier à l'échelle nationale (RDC) "
            "ou internationale (CIJ, CPI, OHADA, etc.)."
        )
        current_jurisdiction = (self.instance.jurisdiction if self.instance.pk else "") or ""
        self.fields["jurisdiction"].choices = court_choices_with_value(current_jurisdiction)
        ensure_default_legal_practice_areas()
        area_names = list(
            LegalPracticeArea.objects.filter(is_active=True)
            .order_by("name")
            .values_list("name", "name")
        )
        current_area = (self.instance.practice_area if self.instance.pk else "") or ""
        if current_area and current_area not in {item[0] for item in area_names}:
            area_names.insert(0, (current_area, current_area))
        self.fields["practice_area"] = forms.ChoiceField(
            label=_("Matière / domaine"),
            required=False,
            choices=[("", _("— Choisir une matière —")), *area_names],
            widget=forms.Select(attrs={"class": "form-input"}),
        )
        if current_area:
            self.fields["practice_area"].initial = current_area
        self.order_fields(
            [
                "title",
                "scale",
                "jurisdiction",
                "practice_area",
                "description",
                "status",
                "opened_at",
                "closed_at",
                "initial_pdf",
                "notes",
            ]
        )
    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        scale = cleaned.get("scale") or MatterScale.NATIONAL
        jurisdiction = (cleaned.get("jurisdiction") or "").strip()
        try:
            validate_matter_scale(scale=scale, jurisdiction=jurisdiction)
        except ValidationError as exc:
            for field, errors in exc.message_dict.items():
                for err in errors:
                    self.add_error(field, err)
        return cleaned


class MatterLawyerAssignForm(forms.Form):
    """Affectation d'un ou plusieurs avocats du cabinet à un dossier."""

    lawyers = forms.ModelMultipleChoiceField(
        label=_("Avocats"),
        queryset=User.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
    )
    lead = forms.ModelChoiceField(
        label=_("Responsable"),
        queryset=User.objects.none(),
        required=False,
        empty_label=_("— Premier sélectionné —"),
        widget=forms.Select(attrs={"class": "form-input"}),
    )

    def __init__(self, *args: Any, lawyer_queryset: QuerySet[Any] | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        qs = lawyer_queryset if lawyer_queryset is not None else User.objects.none()
        self.fields["lawyers"].queryset = qs
        self.fields["lead"].queryset = qs

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        lawyers = list(cleaned.get("lawyers") or [])
        lead = cleaned.get("lead")
        # Par défaut : le responsable est le premier avocat sélectionné s'il n'en fait pas partie.
        if lawyers and (lead is None or lead not in lawyers):
            cleaned["lead"] = lawyers[0]
        return cleaned
