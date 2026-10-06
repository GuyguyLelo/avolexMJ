"""Catalogue des juridictions (référentiel plateforme)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.utils.text import slugify
from django.utils.translation import gettext as _g
from django.utils.translation import gettext_lazy as _

from apps.tenants.models import Jurisdiction, JurisdictionScale

if TYPE_CHECKING:
    from apps.tenants.models import Jurisdiction as JurisdictionType


def iter_default_jurisdictions() -> list[tuple[str, str, str]]:
    """Juridictions initiales : (nom, groupe, échelle)."""
    from apps.core.kinshasa_courts import INTERNATIONAL_COURT_GROUPS, national_court_groups

    rows: list[tuple[str, str, str]] = []
    for group, items in national_court_groups():
        category = str(group)
        for value, _label in items:
            rows.append((value, category, JurisdictionScale.NATIONAL))
    for group, items in INTERNATIONAL_COURT_GROUPS:
        category = str(group)
        for value, _label in items:
            rows.append((value, category, JurisdictionScale.INTERNATIONAL))
    return rows


def ensure_default_jurisdictions() -> list[Jurisdiction]:
    """Crée les juridictions du référentiel si elles n'existent pas encore."""
    created: list[Jurisdiction] = []
    for name, category, scale in iter_default_jurisdictions():
        item = Jurisdiction.objects.filter(name=name).first()
        if item is None:
            item = Jurisdiction(
                name=name,
                slug=_unique_slug(name),
                category=category,
                scale=scale,
                is_active=True,
            )
            item.save()
        created.append(item)
    return created


def _unique_slug(name: str) -> str:
    base = slugify(name) or "juridiction"
    slug = base
    counter = 1
    while Jurisdiction.all_objects.filter(slug=slug).exists():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def jurisdiction_choice_groups(*, current: str = "") -> list[tuple[str, list[tuple[str, str]]]]:
    """Optgroups pour les listes déroulantes, à partir du référentiel."""
    ensure_default_jurisdictions()
    qs = Jurisdiction.objects.filter(is_active=True).order_by("scale", "category", "name")
    groups: dict[str, list[tuple[str, str]]] = {}
    order: list[str] = []
    names: set[str] = set()
    for item in qs:
        names.add(item.name)
        scale_label = _g("Nationale") if item.scale == JurisdictionScale.NATIONAL else _g("Internationale")
        key = f"{scale_label} — {item.category}" if item.category else str(scale_label)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((item.name, item.name))
    if current and current not in names:
        extra_label = _g("Valeur existante")
        groups[extra_label] = [(current, current)]
        order.insert(0, extra_label)
    return [(key, groups[key]) for key in order]


def jurisdiction_choices(*, blank: bool = True, current: str = "") -> list[Any]:
    """Choix Select (optgroups) pour les dossiers."""
    choices: list[Any] = []
    if blank:
        choices.append(("", _("— Sélectionner un tribunal —")))
    choices.extend(jurisdiction_choice_groups(current=current))
    return choices


def jurisdiction_filter_choices() -> list[tuple[str, str]]:
    """Liste plate pour les filtres d'audiences."""
    ensure_default_jurisdictions()
    return [("", _("Tous les tribunaux"))] + list(
        Jurisdiction.objects.filter(is_active=True)
        .order_by("scale", "category", "name")
        .values_list("name", "name")
    )


def national_jurisdiction_names() -> frozenset[str]:
    """Noms des juridictions nationales actives (fallback liste historique)."""
    from apps.core.kinshasa_courts import national_court_values

    names = frozenset(
        Jurisdiction.objects.filter(is_active=True, scale=JurisdictionScale.NATIONAL).values_list(
            "name", flat=True
        )
    )
    return names or national_court_values()


def international_jurisdiction_names() -> frozenset[str]:
    """Noms des juridictions internationales actives (fallback liste historique)."""
    from apps.core.kinshasa_courts import international_court_values

    names = frozenset(
        Jurisdiction.objects.filter(
            is_active=True, scale=JurisdictionScale.INTERNATIONAL
        ).values_list("name", flat=True)
    )
    return names or international_court_values()
