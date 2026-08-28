"""Catalogue des matières juridiques (référentiel plateforme)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.text import slugify

if TYPE_CHECKING:
    from apps.tenants.models import LegalPracticeArea

DEFAULT_LEGAL_PRACTICE_AREAS: tuple[str, ...] = (
    "Droit civil",
    "Droit pénal",
    "Droit commercial",
    "Droit du travail",
    "Droit de la famille",
    "Droit immobilier",
    "Droit des sociétés",
    "Droit OHADA",
    "Droit administratif",
    "Droit des successions",
    "Droit des étrangers",
    "Propriété intellectuelle",
    "Droit pénal international",
    "Droit des contrats",
    "Droit des baux commerciaux",
    "Droit du préjudice corporel",
    "Droit fiscal",
    "Droit minier",
    "Droit de l'environnement",
    "Droit constitutionnel",
)


def ensure_default_legal_practice_areas() -> list[LegalPracticeArea]:
    """Crée les matières du référentiel si elles n'existent pas encore."""
    from apps.tenants.models import LegalPracticeArea

    created: list[LegalPracticeArea] = []
    for name in DEFAULT_LEGAL_PRACTICE_AREAS:
        area = LegalPracticeArea.objects.filter(name=name).first()
        if area is None:
            area = LegalPracticeArea(name=name, slug=_unique_slug(name), is_active=True)
            area.save()
        created.append(area)
    return created


def _unique_slug(name: str) -> str:
    from apps.tenants.models import LegalPracticeArea

    base = slugify(name) or "matiere"
    slug = base
    counter = 1
    while LegalPracticeArea.all_objects.filter(slug=slug).exists():
        slug = f"{base}-{counter}"
        counter += 1
    return slug
