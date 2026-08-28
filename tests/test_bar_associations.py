"""Tests référentiel des barreaux."""

from apps.core.bar_associations import bar_association_values
from apps.tenants.forms import CabinetForm


def test_kinshasa_bar_associations_include_gombe() -> None:
    values = bar_association_values()
    assert "Barreau de Kinshasa/Gombe" in values
    assert len(values) >= 8


def test_cabinet_form_renders_bar_association_select() -> None:
    html = str(CabinetForm()["bar_association"])
    assert "<select" in html
    assert "Barreau de Kinshasa/Gombe" in html
    assert "— Choisir un barreau —" in html
