"""Catalogue des structures / entités étatiques de la RDC."""

from __future__ import annotations

from django.utils.text import slugify
from django.utils.translation import gettext as _g

from apps.tenants.models import StateEntity

# (nom, groupe)
DEFAULT_STATE_ENTITIES: tuple[tuple[str, str], ...] = (
    # État
    ("République Démocratique du Congo", "État"),
    ("Présidence de la République", "Présidence / Primature"),
    ("Primature", "Présidence / Primature"),
    # Institutions
    ("Assemblée nationale", "Institutions constitutionnelles"),
    ("Sénat", "Institutions constitutionnelles"),
    ("Cour constitutionnelle", "Institutions constitutionnelles"),
    ("Cour de cassation", "Institutions constitutionnelles"),
    ("Conseil d'État", "Institutions constitutionnelles"),
    ("Cour des comptes", "Institutions constitutionnelles"),
    ("Conseil supérieur de la magistrature", "Institutions constitutionnelles"),
    ("Commission électorale nationale indépendante (CENI)", "Institutions constitutionnelles"),
    ("Banque centrale du Congo", "Institutions constitutionnelles"),
    ("Inspection générale des finances", "Institutions constitutionnelles"),
    ("Agence nationale de renseignements", "Institutions constitutionnelles"),
    # Ministères
    ("Ministère de la Justice et Garde des Sceaux", "Ministères"),
    ("Ministère de l'Intérieur, Sécurité, Décentralisation et Affaires coutumières", "Ministères"),
    ("Ministère des Affaires étrangères", "Ministères"),
    ("Ministère de la Défense nationale et Anciens combattants", "Ministères"),
    ("Ministère des Finances", "Ministères"),
    ("Ministère du Budget", "Ministères"),
    ("Ministère du Plan", "Ministères"),
    ("Ministère de l'Économie nationale", "Ministères"),
    ("Ministère du Portefeuille", "Ministères"),
    ("Ministère des Mines", "Ministères"),
    ("Ministère des Hydrocarbures", "Ministères"),
    ("Ministère de l'Industrie", "Ministères"),
    ("Ministère du Commerce extérieur", "Ministères"),
    ("Ministère de l'Agriculture", "Ministères"),
    ("Ministère de la Pêche et Élevage", "Ministères"),
    ("Ministère de l'Environnement et Développement durable", "Ministères"),
    ("Ministère des Travaux publics et Infrastructures", "Ministères"),
    ("Ministère des Transports et Voies de communication", "Ministères"),
    ("Ministère de l'Énergie et Ressources hydrauliques", "Ministères"),
    ("Ministère des Affaires foncières", "Ministères"),
    ("Ministère de l'Urbanisme et Habitat", "Ministères"),
    ("Ministère de l'Enseignement primaire, secondaire et technique", "Ministères"),
    ("Ministère de l'Enseignement supérieur et Universitaire", "Ministères"),
    ("Ministère de la Recherche scientifique et Innovation technologique", "Ministères"),
    ("Ministère de la Santé publique, Hygiène et Prévention", "Ministères"),
    ("Ministère des Affaires sociales, Actions humanitaires et Solidarité nationale", "Ministères"),
    ("Ministère du Genre, Famille et Enfant", "Ministères"),
    ("Ministère de l'Emploi, Travail et Prévoyance sociale", "Ministères"),
    ("Ministère de la Fonction publique", "Ministères"),
    ("Ministère de la Formation professionnelle", "Ministères"),
    ("Ministère de la Jeunesse", "Ministères"),
    ("Ministère des Sports et Loisirs", "Ministères"),
    ("Ministère de la Culture, Arts et Patrimoine", "Ministères"),
    ("Ministère de la Communication et Médias", "Ministères"),
    ("Ministère du Numérique", "Ministères"),
    ("Ministère des Postes, Télécommunications et Nouvelles technologies", "Ministères"),
    ("Ministère des Droits humains", "Ministères"),
    ("Ministère de la Décentralisation et Réformes institutionnelles", "Ministères"),
    ("Ministère de l'Intégration régionale", "Ministères"),
    # Entités publiques
    ("Direction générale des impôts (DGI)", "Entités publiques"),
    ("Direction générale des douanes et accises (DGDA)", "Entités publiques"),
    ("Régie des voies aériennes (RVA)", "Entités publiques"),
    ("Régie des voies maritimes (RVM)", "Entités publiques"),
    ("Office des routes", "Entités publiques"),
    ("Société nationale d'électricité (SNEL)", "Entités publiques"),
    ("Régideso", "Entités publiques"),
    ("Office national des transports (ONATRA)", "Entités publiques"),
    ("Fonds de promotion de l'industrie (FPI)", "Entités publiques"),
    ("Caisse nationale de sécurité sociale (CNSS)", "Entités publiques"),
    ("Institut national de sécurité sociale (INSS)", "Entités publiques"),
    ("Police nationale congolaise", "Entités publiques"),
    ("Forces armées de la République Démocratique du Congo (FARDC)", "Entités publiques"),
    # Provinces
    ("Province de Kinshasa", "Provinces"),
    ("Province du Kongo Central", "Provinces"),
    ("Province du Kwango", "Provinces"),
    ("Province du Kwilu", "Provinces"),
    ("Province du Mai-Ndombe", "Provinces"),
    ("Province de l'Équateur", "Provinces"),
    ("Province du Sud-Ubangi", "Provinces"),
    ("Province du Nord-Ubangi", "Provinces"),
    ("Province de la Mongala", "Provinces"),
    ("Province de la Tshuapa", "Provinces"),
    ("Province de la Tshopo", "Provinces"),
    ("Province du Bas-Uele", "Provinces"),
    ("Province du Haut-Uele", "Provinces"),
    ("Province de l'Ituri", "Provinces"),
    ("Province du Nord-Kivu", "Provinces"),
    ("Province du Sud-Kivu", "Provinces"),
    ("Province du Maniema", "Provinces"),
    ("Province du Haut-Katanga", "Provinces"),
    ("Province du Lualaba", "Provinces"),
    ("Province du Haut-Lomami", "Provinces"),
    ("Province du Tanganyika", "Provinces"),
    ("Province du Lomami", "Provinces"),
    ("Province du Kasaï", "Provinces"),
    ("Province du Kasaï Central", "Provinces"),
    ("Province du Kasaï Oriental", "Provinces"),
    ("Province du Sankuru", "Provinces"),
)


def iter_default_state_entities() -> list[tuple[str, str]]:
    """Entités initiales : (nom, groupe)."""
    return list(DEFAULT_STATE_ENTITIES)


def ensure_default_state_entities() -> list[StateEntity]:
    """Crée les structures étatiques RDC si elles n'existent pas encore."""
    created: list[StateEntity] = []
    for name, category in iter_default_state_entities():
        item = StateEntity.objects.filter(name=name).first()
        if item is None:
            item = StateEntity(
                name=name,
                slug=_unique_slug(name),
                category=category,
                is_active=True,
            )
            item.save()
        elif item.category != category:
            item.category = category
            item.save(update_fields=["category", "updated_at"])
        created.append(item)
    return created


def _unique_slug(name: str) -> str:
    base = slugify(name) or "entite-etatique"
    slug = base
    counter = 1
    while StateEntity.all_objects.filter(slug=slug).exists():
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def state_entity_choices(*, current: str = "") -> list[tuple[str, str]]:
    """Choix plats pour listes déroulantes (valeur = nom)."""
    ensure_default_state_entities()
    qs = StateEntity.objects.filter(is_active=True).order_by("category", "name")
    choices = [(item.name, item.name) for item in qs]
    names = {name for name, _ in choices}
    if current and current not in names:
        choices.insert(0, (current, current))
    return choices


def state_entity_choice_groups(*, current: str = "") -> list[tuple[str, list[tuple[str, str]]]]:
    """Optgroups par catégorie pour le formulaire dossier."""
    ensure_default_state_entities()
    qs = StateEntity.objects.filter(is_active=True).order_by("category", "name")
    groups: dict[str, list[tuple[str, str]]] = {}
    order: list[str] = []
    names: set[str] = set()
    for item in qs:
        names.add(item.name)
        key = item.category or _g("Autres")
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((item.name, item.name))
    if current and current not in names:
        extra = _g("Valeur existante")
        groups[extra] = [(current, current)]
        order.insert(0, extra)
    return [(key, groups[key]) for key in order]
