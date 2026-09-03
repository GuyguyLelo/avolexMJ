"""Widgets formulaires transverses."""

from __future__ import annotations

from typing import Any

from django import forms
from django.forms.widgets import ClearableFileInput


class PrivateClearableFileInput(ClearableFileInput):
    """Fichier effaçable sans lien public (stockage privé)."""

    template_name = "forms/widgets/private_clearable_file_input.html"

    def is_initial(self, value: Any) -> bool:
        return bool(value and getattr(value, "name", None))

    def get_context(self, name: str, value: Any, attrs: dict[str, Any] | None) -> dict[str, Any]:
        context = super().get_context(name, value, attrs)
        widget = context["widget"]
        if self.is_initial(value):
            widget["filename"] = getattr(value, "name", str(value))
        return context
