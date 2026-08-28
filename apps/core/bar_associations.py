"""Barreaux d'avocats (RDC — Kinshasa).

Référentiel aligné sur les circonscriptions judiciaires de Kinshasa.
"""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

KINSHASA_BAR_ASSOCIATIONS: list[tuple[str, str]] = [
    ("Barreau de Kinshasa/Gombe", _("Barreau de Kinshasa/Gombe")),
    ("Barreau de Kinshasa/Matete", _("Barreau de Kinshasa/Matete")),
    ("Barreau de Kinshasa/Kalamu", _("Barreau de Kinshasa/Kalamu")),
    ("Barreau de Kinshasa/N'djili", _("Barreau de Kinshasa/N'djili")),
    ("Barreau de Kinshasa/Kinkole", _("Barreau de Kinshasa/Kinkole")),
    ("Barreau de Kinshasa/Lemba", _("Barreau de Kinshasa/Lemba")),
    ("Barreau de Kinshasa/Ngaliema", _("Barreau de Kinshasa/Ngaliema")),
    ("Barreau de Kinshasa/Mont Ngafula", _("Barreau de Kinshasa/Mont Ngafula")),
    ("Barreau de Kinshasa/Selembao", _("Barreau de Kinshasa/Selembao")),
    ("Barreau de Kinshasa/Masina", _("Barreau de Kinshasa/Masina")),
]


def bar_association_values() -> frozenset[str]:
    """Ensemble des barreaux enregistrables."""
    return frozenset(value for value, _label in KINSHASA_BAR_ASSOCIATIONS)


def bar_association_choices(*, blank: bool = True) -> list[tuple[str, str]]:
    """Choix pour un widget Select."""
    choices: list[tuple[str, str]] = []
    if blank:
        choices.append(("", _("— Choisir un barreau —")))
    choices.extend(KINSHASA_BAR_ASSOCIATIONS)
    return choices


def bar_association_choices_with_value(current: str, *, blank: bool = True) -> list[tuple[str, str]]:
    """Inclut une valeur existante hors liste (données antérieures)."""
    known = bar_association_values()
    choices = bar_association_choices(blank=blank)
    if current and current not in known:
        insert_at = 1 if blank else 0
        choices.insert(insert_at, (current, current))
    return choices
