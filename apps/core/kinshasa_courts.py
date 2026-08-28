"""Tribunaux et juridictions de Kinshasa (RDC).

Références : décret n°14/015 du 08/05/2014 (TGI), arrêté portant création
des tribunaux de paix à Kinshasa, organisation judiciaire congolaise.
"""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

# Groupes affichés en optgroup dans les listes déroulantes.
KINSHASA_COURT_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        _("Cours suprêmes"),
        [
            ("Cour de cassation", _("Cour de cassation")),
        ],
    ),
    (
        _("Cours d'appel"),
        [
            ("Cour d'appel de Kinshasa/Gombe", _("Cour d'appel de Kinshasa/Gombe")),
            ("Cour d'appel de Kinshasa/Matete", _("Cour d'appel de Kinshasa/Matete")),
        ],
    ),
    (
        _("Tribunaux de grande instance"),
        [
            (
                "Tribunal de grande instance de Kinshasa/Gombe",
                _("Tribunal de grande instance de Kinshasa/Gombe"),
            ),
            (
                "Tribunal de grande instance de Kinshasa/Kalamu",
                _("Tribunal de grande instance de Kinshasa/Kalamu"),
            ),
            (
                "Tribunal de grande instance de Kinshasa/N'djili",
                _("Tribunal de grande instance de Kinshasa/N'djili"),
            ),
            (
                "Tribunal de grande instance de Kinshasa/Kinkole",
                _("Tribunal de grande instance de Kinshasa/Kinkole"),
            ),
        ],
    ),
    (
        _("Tribunaux de paix"),
        [
            (
                "Tribunal de paix de Kinshasa/Ngaliema",
                _("Tribunal de paix de Kinshasa/Ngaliema"),
            ),
            (
                "Tribunal de paix de Kinshasa/Assossa",
                _("Tribunal de paix de Kinshasa/Assossa"),
            ),
            (
                "Tribunal de paix de Kinshasa/Pont Kasa-Vubu",
                _("Tribunal de paix de Kinshasa/Pont Kasa-Vubu"),
            ),
            ("Tribunal de paix de Kinshasa/Gombe", _("Tribunal de paix de Kinshasa/Gombe")),
            ("Tribunal de paix de Kinshasa/Lemba", _("Tribunal de paix de Kinshasa/Lemba")),
            ("Tribunal de paix de Kinshasa/Matete", _("Tribunal de paix de Kinshasa/Matete")),
            ("Tribunal de paix de Kinshasa/N'djili", _("Tribunal de paix de Kinshasa/N'djili")),
            (
                "Tribunal de paix de Kinshasa/Kinkole",
                _("Tribunal de paix de Kinshasa/Kinkole"),
            ),
        ],
    ),
    (
        _("Juridictions spécialisées"),
        [
            ("Tribunal de commerce de la Gombe", _("Tribunal de commerce de la Gombe")),
            ("Tribunal du travail de la Gombe", _("Tribunal du travail de la Gombe")),
            (
                "Tribunal pour enfants de la Gombe",
                _("Tribunal pour enfants de la Gombe"),
            ),
        ],
    ),
]

NATIONAL_INSTITUTION_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        _("National — institutions de la République"),
        [
            ("Cour constitutionnelle", _("Cour constitutionnelle")),
            ("Conseil d'État", _("Conseil d'État")),
            ("Cour des comptes", _("Cour des comptes")),
        ],
    ),
]

INTERNATIONAL_COURT_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        _("International — juridictions mondiales"),
        [
            ("Cour internationale de Justice", _("Cour internationale de Justice")),
            ("Cour pénale internationale", _("Cour pénale internationale")),
        ],
    ),
    (
        _("International — Afrique et OHADA"),
        [
            (
                "Cour commune de justice et d'arbitrage (OHADA)",
                _("Cour commune de justice et d'arbitrage (OHADA)"),
            ),
            (
                "Cour africaine des droits de l'homme et des peuples",
                _("Cour africaine des droits de l'homme et des peuples"),
            ),
            (
                "Cour de justice de l'Union africaine",
                _("Cour de justice de l'Union africaine"),
            ),
            ("Cour de justice du COMESA", _("Cour de justice du COMESA")),
        ],
    ),
    (
        _("International — arbitrage et investissements"),
        [
            (
                "Centre international pour le règlement des différends relatifs aux investissements (CIRDI)",
                _("CIRDI (Banque mondiale)"),
            ),
            ("Cour d'arbitrage de la CCI", _("Cour d'arbitrage de la CCI")),
            ("Tribunal arbitral CNUDCI", _("Tribunal arbitral CNUDCI")),
        ],
    ),
]


def national_court_groups() -> list[tuple[str, list[tuple[str, str]]]]:
    """Juridictions de l'échelle nationale (RDC)."""
    labeled: list[tuple[str, list[tuple[str, str]]]] = list(NATIONAL_INSTITUTION_GROUPS)
    for group, items in KINSHASA_COURT_GROUPS:
        labeled.append((f"{_('National')} — {group}", items))
    return labeled


def all_court_groups() -> list[tuple[str, list[tuple[str, str]]]]:
    """Juridictions nationales et internationales."""
    return national_court_groups() + INTERNATIONAL_COURT_GROUPS


def international_court_values() -> frozenset[str]:
    """Libellés des juridictions internationales."""
    return frozenset(
        value for _group, items in INTERNATIONAL_COURT_GROUPS for value, _label in items
    )


def national_court_values() -> frozenset[str]:
    """Libellés des juridictions nationales."""
    extra = frozenset(
        value for _group, items in NATIONAL_INSTITUTION_GROUPS for value, _label in items
    )
    return kinshasa_court_values() | extra


def kinshasa_court_choices(*, blank: bool = True) -> list[tuple[str, str] | tuple[str, list]]:
    """Choix pour un widget Select (optgroups nationales et internationales)."""
    choices: list[tuple[str, str] | tuple[str, list]] = []
    if blank:
        choices.append(("", _("— Sélectionner un tribunal —")))
    choices.extend(all_court_groups())
    return choices


def kinshasa_court_values() -> frozenset[str]:
    """Ensemble des libellés enregistrables (Kinshasa)."""
    return frozenset(value for _group, items in KINSHASA_COURT_GROUPS for value, _label in items)


def all_court_values() -> frozenset[str]:
    """Tous les libellés nationaux et internationaux."""
    return national_court_values() | international_court_values()


def kinshasa_court_filter_choices() -> list[tuple[str, str]]:
    """Liste plate pour filtres (tous les tribunaux + option vide)."""
    return [("", _("Tous les tribunaux"))] + [
        (value, label) for _group, items in all_court_groups() for value, label in items
    ]


def court_choices_with_value(current: str, *, blank: bool = True) -> list:
    """Inclut une valeur existante hors liste (données antérieures)."""
    known = all_court_values()
    choices = kinshasa_court_choices(blank=blank)
    if current and current not in known:
        insert_at = 1 if blank else 0
        choices.insert(insert_at, (current, current))
    return choices
