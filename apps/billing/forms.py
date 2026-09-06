"""Formulaires facturation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django import forms
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.billing.services import default_hourly_rate, default_tax_rate
from apps.matters.models import Matter


class TimeEntryForm(forms.Form):
    """Saisie manuelle de temps."""

    matter = forms.ModelChoiceField(
        label=_("Dossier"),
        queryset=Matter.objects.none(),
        widget=forms.Select(attrs={"class": "form-input"}),
    )
    description = forms.CharField(
        label=_("Description"),
        max_length=500,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    duration_minutes = forms.IntegerField(
        label=_("Durée (minutes)"),
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "form-input"}),
    )
    hourly_rate = forms.DecimalField(
        label=_("Taux horaire ($)"),
        max_digits=10,
        decimal_places=2,
        initial=default_hourly_rate,
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
    )
    is_billable = forms.BooleanField(
        label=_("Facturable"),
        required=False,
        initial=True,
        widget=forms.CheckboxInput(),
    )

    def __init__(
        self, *args: Any, matter_queryset: QuerySet[Matter] | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        if matter_queryset is not None:
            self.fields["matter"].queryset = matter_queryset


class TimerStartForm(forms.Form):
    """Démarrage d'un timer."""

    matter = forms.ModelChoiceField(
        label=_("Dossier"),
        queryset=Matter.objects.none(),
        widget=forms.Select(attrs={"class": "form-input"}),
    )
    description = forms.CharField(
        label=_("Description"),
        max_length=500,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )

    def __init__(
        self, *args: Any, matter_queryset: QuerySet[Matter] | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        if matter_queryset is not None:
            self.fields["matter"].queryset = matter_queryset


class ExpenseForm(forms.Form):
    """Saisie de débours."""

    matter = forms.ModelChoiceField(
        label=_("Dossier"),
        queryset=Matter.objects.none(),
        widget=forms.Select(attrs={"class": "form-input"}),
    )
    description = forms.CharField(
        label=_("Description"),
        max_length=500,
        widget=forms.TextInput(attrs={"class": "form-input"}),
    )
    amount = forms.DecimalField(
        label=_("Montant ($)"),
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
    )
    incurred_on = forms.DateField(
        label=_("Date"),
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={"class": "form-input", "type": "date"}),
    )
    is_billable = forms.BooleanField(label=_("Facturable"), required=False, initial=True)

    def __init__(
        self, *args: Any, matter_queryset: QuerySet[Matter] | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        if matter_queryset is not None:
            self.fields["matter"].queryset = matter_queryset


class InvoiceCreateForm(forms.Form):
    """Création d'une facture brouillon."""

    matter = forms.ModelChoiceField(
        label=_("Dossier"),
        queryset=Matter.objects.none(),
        widget=forms.Select(attrs={"class": "form-input"}),
    )
    tax_rate = forms.DecimalField(
        label=_("TVA (%)"),
        max_digits=5,
        decimal_places=2,
        initial=default_tax_rate,
        widget=forms.NumberInput(attrs={"class": "form-input", "step": "0.01"}),
    )
    notes = forms.CharField(
        label=_("Notes"),
        required=False,
        widget=forms.Textarea(attrs={"class": "form-input", "rows": 3}),
    )
    time_entries = forms.MultipleChoiceField(
        label=_("Temps à facturer"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    expenses = forms.MultipleChoiceField(
        label=_("Débours à facturer"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(
        self,
        *args: Any,
        matter_queryset: QuerySet[Matter] | None = None,
        time_choices: list[tuple[str, str]] | None = None,
        expense_choices: list[tuple[str, str]] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        if matter_queryset is not None:
            self.fields["matter"].queryset = matter_queryset
        self.fields["time_entries"].choices = time_choices or []
        self.fields["expenses"].choices = expense_choices or []
