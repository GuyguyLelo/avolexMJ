"""Formulaires dossiers."""

from __future__ import annotations

from typing import Any

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from apps.clients.models import Client
from apps.core.kinshasa_courts import court_choices_with_value
from apps.matters.models import Matter, MatterScale, MatterStatus
from apps.matters.services import validate_matter_scale
from apps.tenants.legal_areas import ensure_default_legal_practice_areas
from apps.tenants.models import Cabinet, LegalPracticeArea

User = get_user_model()


class MatterForm(forms.ModelForm):
    """Création / édition d'un dossier."""

    jurisdiction = forms.ChoiceField(
        label=_("juridiction"),
        required=False,
        choices=[],
        widget=forms.Select(attrs={"class": "form-input"}),
    )

    class Meta:
        model = Matter
        fields = (
            "client",
            "title",
            "scale",
            "description",
            "practice_area",
            "jurisdiction",
            "opposing_party",
            "status",
            "responsible_lawyer",
            "opened_at",
            "closed_at",
            "notes",
        )
        widgets = {
            "client": forms.Select(attrs={"class": "form-input"}),
            "title": forms.TextInput(attrs={"class": "form-input"}),
            "scale": forms.Select(attrs={"class": "form-input"}),
            "description": forms.Textarea(attrs={"class": "form-input", "rows": 4}),
            "practice_area": forms.Select(attrs={"class": "form-input"}),
            "opposing_party": forms.TextInput(attrs={"class": "form-input"}),
            "status": forms.Select(attrs={"class": "form-input"}),
            "responsible_lawyer": forms.Select(attrs={"class": "form-input"}),
            "opened_at": forms.DateInput(attrs={"class": "form-input", "type": "date"}),
            "closed_at": forms.DateInput(attrs={"class": "form-input", "type": "date"}),
            "notes": forms.Textarea(attrs={"class": "form-input", "rows": 3}),
        }

    def __init__(
        self,
        *args: Any,
        client_queryset: QuerySet[Client] | None = None,
        lawyer_queryset: QuerySet[Any] | None = None,
        include_cabinet: bool = False,
        cabinets: QuerySet[Cabinet] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        if client_queryset is not None:
            self.fields["client"].queryset = client_queryset
        if lawyer_queryset is not None:
            self.fields["responsible_lawyer"].queryset = lawyer_queryset
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
            label=_("matière / domaine"),
            required=False,
            choices=[("", _("— Choisir une matière —")), *area_names],
            widget=forms.Select(attrs={"class": "form-input"}),
        )
        if current_area:
            self.fields["practice_area"].initial = current_area
        if include_cabinet:
            cabinet_qs = (
                cabinets if cabinets is not None else Cabinet.objects.filter(is_active=True)
            )
            self.fields["target_cabinet"] = forms.ModelChoiceField(
                label=_("Cabinet destinataire"),
                queryset=cabinet_qs.order_by("name"),
                required=True,
                widget=forms.Select(attrs={"class": "form-input"}),
                help_text=_(
                    "Choix obligatoire : le dossier sera ouvert dans ce cabinet. "
                    "Les cabinets spécialisés sont proposés selon la matière."
                ),
            )
            self.order_fields(
                [
                    "practice_area",
                    "target_cabinet",
                    "client",
                    "title",
                    "scale",
                    "description",
                    "jurisdiction",
                    "opposing_party",
                    "status",
                    "responsible_lawyer",
                    "opened_at",
                    "closed_at",
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
