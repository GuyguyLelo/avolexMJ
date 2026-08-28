"""Formulaires agenda."""

from __future__ import annotations

from typing import Any

from django import forms
from django.db.models import QuerySet
from django.utils.translation import gettext_lazy as _

from apps.calendar_app.models import Event, EventType, HearingStatus
from apps.core.kinshasa_courts import court_choices_with_value
from apps.matters.models import Matter


class EventForm(forms.ModelForm):
    """Création / édition d'événement ou tâche."""

    class Meta:
        model = Event
        fields = (
            "event_type",
            "title",
            "matter",
            "description",
            "starts_at",
            "ends_at",
            "all_day",
            "location",
            "remind_at",
        )
        widgets = {
            "event_type": forms.Select(attrs={"class": "form-input"}),
            "title": forms.TextInput(attrs={"class": "form-input"}),
            "matter": forms.Select(attrs={"class": "form-input"}),
            "description": forms.Textarea(attrs={"class": "form-input", "rows": 3}),
            "starts_at": forms.DateTimeInput(
                attrs={"class": "form-input", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "ends_at": forms.DateTimeInput(
                attrs={"class": "form-input", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "all_day": forms.CheckboxInput(),
            "location": forms.TextInput(attrs={"class": "form-input"}),
            "remind_at": forms.DateTimeInput(
                attrs={"class": "form-input", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
        }

    def __init__(
        self,
        *args: Any,
        matter_queryset: QuerySet[Matter] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields["starts_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"]
        self.fields["ends_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"]
        self.fields["remind_at"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"]
        self.fields["event_type"].choices = EventType.choices
        if matter_queryset is not None:
            self.fields["matter"].queryset = matter_queryset
            self.fields["matter"].required = False


class HearingForm(forms.ModelForm):
    """Création / édition d'une audience judiciaire."""

    court = forms.ChoiceField(
        label=_("tribunal"),
        required=False,
        choices=[],
        widget=forms.Select(attrs={"class": "form-input"}),
    )
    report_file = forms.FileField(
        label=_("Rapport (Word ou PDF)"),
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                "class": "form-input",
                "accept": (
                    ".pdf,.doc,.docx,application/pdf,application/msword,"
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
            }
        ),
        help_text=_("Fichier PDF, DOC ou DOCX."),
    )

    class Meta:
        model = Event
        fields = (
            "title",
            "matter",
            "description",
            "starts_at",
            "ends_at",
            "all_day",
            "court",
            "chamber",
            "location",
            "hearing_status",
            "remind_at",
        )
        widgets = {
            "title": forms.TextInput(
                attrs={"class": "form-input", "placeholder": _("Ex. Audience de mise en état")},
            ),
            "matter": forms.Select(attrs={"class": "form-input"}),
            "description": forms.Textarea(attrs={"class": "form-input", "rows": 3}),
            "starts_at": forms.DateTimeInput(
                attrs={"class": "form-input", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "ends_at": forms.DateTimeInput(
                attrs={"class": "form-input", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "all_day": forms.CheckboxInput(),
            "chamber": forms.TextInput(
                attrs={"class": "form-input", "placeholder": _("Ex. 3e chambre civile")},
            ),
            "location": forms.TextInput(
                attrs={"class": "form-input", "placeholder": _("Ex. Salle 12")},
            ),
            "hearing_status": forms.Select(attrs={"class": "form-input"}),
            "remind_at": forms.DateTimeInput(
                attrs={"class": "form-input", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
        }

    def __init__(
        self,
        *args: Any,
        matter_queryset: QuerySet[Matter] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        for field_name in ("starts_at", "ends_at", "remind_at"):
            self.fields[field_name].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"]
        self.fields["hearing_status"].choices = HearingStatus.choices
        current_court = (self.instance.court if self.instance.pk else "") or ""
        self.fields["court"].choices = court_choices_with_value(current_court)
        if matter_queryset is not None:
            self.fields["matter"].queryset = matter_queryset
        if not self.instance.pk:
            self.fields["hearing_status"].initial = HearingStatus.SCHEDULED
            self.fields.pop("report_file", None)

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        if not cleaned.get("title", "").strip():
            self.add_error("title", _("L'intitulé de l'audience est obligatoire."))
        if not cleaned.get("starts_at"):
            self.add_error("starts_at", _("La date et l'heure sont obligatoires."))
        return cleaned

    def clean_report_file(self) -> object:
        uploaded = self.cleaned_data.get("report_file")
        if uploaded:
            from apps.calendar_app.services import validate_hearing_report_file

            validate_hearing_report_file(uploaded)
        return uploaded
