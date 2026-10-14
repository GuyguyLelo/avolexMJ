"""Charge des données de démonstration pour un cabinet de test."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.billing.models import InvoiceStatus
from apps.billing.services import (
    allocate_invoice_number,
    create_draft_invoice,
    create_expense,
    create_time_entry,
    mark_invoice_overdue,
    mark_invoice_paid,
    render_invoice_pdf_bytes,
    store_invoice_pdf,
)
from apps.calendar_app.models import Event, EventType
from apps.calendar_app.services import create_event
from apps.clients.models import Client, ClientType
from apps.clients.services import create_client
from apps.documents.models import Document
from apps.documents.services import create_document_with_file
from apps.matters.models import Matter, MatterScale, MatterStatus
from apps.matters.services import create_matter, update_matter
from apps.tenants.context import cabinet_context
from apps.tenants.jurisdictions import ensure_default_jurisdictions
from apps.tenants.state_entities import ensure_default_state_entities
from apps.tenants.models import Cabinet, Invitation, Membership
from apps.tenants.roles import Role
from apps.tenants.services import create_cabinet_with_owner, invite_member

User = get_user_model()

DEMO_PASSWORD = "@12345678"  # noqa: S105 — compte de démo local uniquement
DEMO_EMAIL = "ngamika@gmail.com"
MINISTRY_EMAIL = "Admin"
CONSEILLER_EMAIL = "Conseiller"
DIRCABA_EMAIL = "Dircaba"
DEMO_CABINET_NAME = "ILEO Law Firm"
DEMO_CABINET_LEGAL_NAME = "ILEO Law Firm"

TEAM: list[dict[str, str]] = [
    {
        "email": DEMO_EMAIL,
        "first_name": "Camille",
        "last_name": "Dupont",
        "role": Role.CAIMAN,
    },
    {
        "email": "avocat@avolex.local",
        "first_name": "Antoine",
        "last_name": "Lefèvre",
        "role": Role.LAWYER,
    },
]

# Cabinets kinois publics (adresses de leurs sites / barreau) — démo supervision.
KINSHASA_CABINETS: list[dict[str, Any]] = [
    {
        "name": "Peter Kazadi Kankonde & Associés",
        "legal_name": "Cabinet Peter Kazadi Kankonde & Associés",
        "bar_association": "Barreau de Kinshasa/Gombe",
        "address_line1": "52, avenue de la Gombe, 1er niveau",
        "address_line2": "Commune de la Gombe",
        "owner_email": "owner.kazadi@avolex.local",
        "owner_first_name": "Peter",
        "owner_last_name": "Kazadi",
        "client_first_name": "Grace",
        "client_last_name": "Ilunga",
        "matter_title": "Contentieux commercial — Gombe",
        "jurisdiction": "Tribunal de commerce de la Gombe",
        "specialties": ("Droit commercial", "Droit des sociétés", "Droit des contrats"),
    },
    {
        "name": "Cabinet Bâtonnier Jean Claude Mbaki & Associés",
        "legal_name": "Cabinet Bâtonnier Jean Claude MBAKI & Associés",
        "bar_association": "Barreau de Kinshasa/Gombe",
        "address_line1": "1060/B, avenue Colonel Ebeya, quartier Golf",
        "address_line2": "Commune de la Gombe",
        "owner_email": "owner.mbaki@avolex.local",
        "owner_first_name": "Jean-Claude",
        "owner_last_name": "Mbaki",
        "client_first_name": "Patrick",
        "client_last_name": "Kalala",
        "matter_title": "Contentieux administratif OHADA",
        "jurisdiction": "Tribunal de grande instance de Kinshasa/Gombe",
        "specialties": ("Droit administratif", "Droit OHADA", "Droit civil"),
    },
    {
        "name": "Tshibangu Ilunga & Partners",
        "legal_name": "TI&A SCA Tshibangu Ilunga & Associés",
        "bar_association": "Barreau de Kinshasa/Gombe",
        "address_line1": "130/A, boulevard du 30 Juin, immeuble Sanash, suite 7D",
        "address_line2": "Commune de la Gombe",
        "owner_email": "owner.tshibangu@avolex.local",
        "owner_first_name": "Moïse",
        "owner_last_name": "Tshibangu",
        "client_first_name": "Amina",
        "client_last_name": "Mwamba",
        "matter_title": "Litige minier et fiscal",
        "jurisdiction": "Tribunal de commerce de la Gombe",
        "specialties": ("Droit minier", "Droit fiscal", "Droit commercial"),
    },
    {
        "name": "Cabinet Mavinga Declerc & Partners",
        "legal_name": "Cabinet Mavinga Declerc & Partners AARPI",
        "bar_association": "Barreau de Kinshasa/Gombe",
        "address_line1": "1er étage, immeuble Parkland, 1 avenue Ngongo-Lutete",
        "address_line2": "Concession RAFI (ex-PLC), commune de la Gombe",
        "owner_email": "owner.mavinga@avolex.local",
        "owner_first_name": "Declerc",
        "owner_last_name": "Mavinga",
        "client_first_name": "Joseph",
        "client_last_name": "Lutete",
        "matter_title": "Droit des hydrocarbures et marchés publics",
        "jurisdiction": "Tribunal de grande instance de Kinshasa/Gombe",
        "specialties": ("Droit administratif", "Droit commercial", "Droit minier"),
    },
    {
        "name": "Emery Mukendi Wafwana & Associates",
        "legal_name": "Emery Mukendi Wafwana & Associés",
        "bar_association": "Barreau de Kinshasa/Gombe",
        "address_line1": "Crown Tower, 7e niveau, suites 701-702",
        "address_line2": "Croisement boulevard du 30 Juin / avenue Batetela, Gombe",
        "owner_email": "owner.emery@avolex.local",
        "owner_first_name": "Emery",
        "owner_last_name": "Mukendi",
        "client_first_name": "Sarah",
        "client_last_name": "Kabasele",
        "matter_title": "Arbitrage OHADA — investissement",
        "jurisdiction": "Cour commune de justice et d'arbitrage (OHADA)",
        "scale": MatterScale.INTERNATIONAL,
        "specialties": ("Droit OHADA", "Droit commercial", "Droit pénal international"),
    },
]

PERSONS: list[dict[str, Any]] = [
    {
        "first_name": "Julie",
        "last_name": "Martin",
        "email": "julie.martin@example.com",
        "phone": "0612345678",
        "address_line1": "12 rue de la Paix",
        "postal_code": "75002",
        "city": "Paris",
        "birth_date": date(1987, 4, 12),
        "notes": "Cliente historique. Prudente sur les honoraires.",
    },
    {
        "first_name": "Karim",
        "last_name": "Benali",
        "email": "karim.benali@example.com",
        "phone": "0678451230",
        "address_line1": "8 boulevard Voltaire",
        "postal_code": "75011",
        "city": "Paris",
        "notes": "Contentieux prud'homal en cours.",
    },
    {
        "first_name": "Sophie",
        "last_name": "Leroux",
        "email": "sophie.leroux@example.com",
        "phone": "0621987744",
        "address_line1": "3 place Bellecour",
        "postal_code": "69002",
        "city": "Lyon",
        "notes": "Divorce amiable, enfants mineurs.",
    },
    {
        "first_name": "Étienne",
        "last_name": "Moreau",
        "email": "etienne.moreau@example.com",
        "phone": "0611023344",
        "address_line1": "22 rue Sainte-Catherine",
        "postal_code": "33000",
        "city": "Bordeaux",
        "notes": "Litige voisinage / servitude.",
    },
    {
        "first_name": "Inès",
        "last_name": "Diallo",
        "email": "ines.diallo@example.com",
        "phone": "0788123400",
        "address_line1": "14 rue de la République",
        "postal_code": "13001",
        "city": "Marseille",
        "notes": "Droit des étrangers — titre de séjour.",
    },
    {
        "first_name": "Paul",
        "last_name": "Girard",
        "email": "paul.girard@example.com",
        "phone": "0644556677",
        "address_line1": "9 rue des Carmes",
        "postal_code": "44000",
        "city": "Nantes",
        "notes": "Accident de la circulation, expertise en cours.",
    },
    {
        "first_name": "Claire",
        "last_name": "Rousseau",
        "email": "claire.rousseau@example.com",
        "phone": "0699001122",
        "address_line1": "5 allée de la Forêt",
        "postal_code": "67000",
        "city": "Strasbourg",
        "notes": "Succession familiale, 3 héritiers.",
    },
    {
        "first_name": "Hugo",
        "last_name": "Petit",
        "email": "hugo.petit@example.com",
        "phone": "0655332211",
        "address_line1": "17 rue Nationale",
        "postal_code": "59000",
        "city": "Lille",
        "notes": "Bail commercial, impayés de loyer.",
    },
]

COMPANIES: list[dict[str, Any]] = [
    {
        "company_name": "TechNova SAS",
        "legal_form": "SAS",
        "siret": "81234567800012",
        "email": "contact@technova.example",
        "phone": "0142000000",
        "address_line1": "45 avenue de l'Opéra",
        "postal_code": "75002",
        "city": "Paris",
        "notes": "Scale-up, 42 salariés. Contentieux fournisseurs.",
    },
    {
        "company_name": "Atelier Lumière SARL",
        "legal_form": "SARL",
        "siret": "49876543200021",
        "email": "juridique@atelier-lumiere.example",
        "phone": "0478123456",
        "address_line1": "18 rue de la Martinière",
        "postal_code": "69001",
        "city": "Lyon",
        "notes": "Marque et concurrence déloyale.",
    },
    {
        "company_name": "Nord Logistique SA",
        "legal_form": "SA",
        "siret": "32109876500034",
        "email": "direction@nord-logistique.example",
        "phone": "0320123456",
        "address_line1": "Zone industrielle, rue des Entrepôts",
        "postal_code": "59200",
        "city": "Tourcoing",
        "notes": "Contrats de transport et sous-traitance.",
    },
    {
        "company_name": "Maison Bellevue SCI",
        "legal_form": "SCI",
        "siret": "55443322100018",
        "email": "gerance@maison-bellevue.example",
        "phone": "0556123498",
        "address_line1": "2 chemin des Vignes",
        "postal_code": "33000",
        "city": "Bordeaux",
        "notes": "Gestion immobilière, 4 lots.",
    },
]


class Command(BaseCommand):
    """Crée un cabinet démo avec clients, dossiers, agenda, GED et facturation."""

    help = "Génère des données de test (ILEO + 5 cabinets de Kinshasa/Gombe)."

    def handle(self, *args: object, **options: object) -> None:
        with transaction.atomic():
            self._seed()

    def _seed(self) -> None:
        super_admin = self._ensure_super_admin()
        ministry = self._ensure_ministry()
        conseiller = self._ensure_ministry_role(
            email=CONSEILLER_EMAIL,
            first_name="Paul",
            last_name="Conseiller",
            ministry_role="conseiller",
        )
        dircaba = self._ensure_ministry_role(
            email=DIRCABA_EMAIL,
            first_name="Jeanne",
            last_name="Dircaba",
            ministry_role="dircaba",
        )
        owner = self._ensure_user(
            email=DEMO_EMAIL,
            first_name="Camille",
            last_name="Dupont",
        )
        cabinet = self._ensure_cabinet(owner)
        team = self._ensure_team(cabinet, owner)

        with cabinet_context(cabinet):
            clients = self._ensure_clients(cabinet, owner)
            lawyer = team[Role.LAWYER]
            associate = team[Role.LAWYER]
            matters = self._ensure_matters(cabinet, owner, lawyer, associate, clients, ministry)
            self._ensure_events(cabinet, owner, lawyer, associate, matters)
            self._ensure_time_and_expenses(cabinet, owner, lawyer, associate, matters)
            self._ensure_invoices(cabinet, owner, matters)
            self._ensure_documents(cabinet, owner, matters)
            self._ensure_invitation(cabinet, owner)

        kinshasa = self._ensure_kinshasa_cabinets(ministry)
        self._ensure_practice_areas(cabinet, kinshasa, owner)
        ensure_default_jurisdictions()
        ensure_default_state_entities()

        self.stdout.write(self.style.SUCCESS("Données de test prêtes."))
        self.stdout.write(f"  Cabinet   : {cabinet.name}")
        self.stdout.write("  Comptes (mot de passe identique) :")
        self.stdout.write(f"    {super_admin.email:28}  SuperAdmin      {DEMO_PASSWORD}")
        self.stdout.write(f"    {MINISTRY_EMAIL:28}  administrateur  {DEMO_PASSWORD}")
        self.stdout.write(
            f"    {conseiller.email:28}  Conseiller     {DEMO_PASSWORD}"
        )
        self.stdout.write(f"    {dircaba.email:28}  Dircaba        {DEMO_PASSWORD}")
        for member in TEAM:
            self.stdout.write(f"    {member['email']:28}  {member['role']:14}  {DEMO_PASSWORD}")
        self.stdout.write("  Cabinets Kinshasa/Gombe :")
        for spec, _cab in zip(KINSHASA_CABINETS, kinshasa, strict=True):
            self.stdout.write(f"    {spec['name']}")
            self.stdout.write(f"      {spec['owner_email']:28}  {DEMO_PASSWORD}")

    def _ensure_ministry(self) -> Any:
        from apps.accounts.models import MinistryRole
        from apps.tenants.services import detach_user_from_all_cabinets

        user = self._ensure_user(
            email=MINISTRY_EMAIL,
            first_name="Ministère",
            last_name="Justice",
        )
        changed = False
        if not user.is_platform_admin:
            user.is_platform_admin = True
            changed = True
        if user.ministry_role != MinistryRole.ADMIN:
            user.ministry_role = MinistryRole.ADMIN
            changed = True
        if changed:
            user.save(update_fields=["is_platform_admin", "ministry_role"])
        detach_user_from_all_cabinets(user)
        return user

    def _ensure_ministry_role(
        self,
        *,
        email: str,
        first_name: str,
        last_name: str,
        ministry_role: str,
    ) -> Any:
        from apps.tenants.services import detach_user_from_all_cabinets

        user = self._ensure_user(
            email=email,
            first_name=first_name,
            last_name=last_name,
        )
        changed = False
        if not user.is_platform_admin:
            user.is_platform_admin = True
            changed = True
        if user.is_super_admin:
            user.is_super_admin = False
            changed = True
        if user.ministry_role != ministry_role:
            user.ministry_role = ministry_role
            changed = True
        if changed:
            user.save(
                update_fields=["is_platform_admin", "is_super_admin", "ministry_role"]
            )
        detach_user_from_all_cabinets(user)
        return user

    def _ensure_super_admin(self) -> Any:
        from apps.tenants.services import detach_user_from_all_cabinets

        user = self._ensure_user(
            email="SuperAdmin",
            first_name="Super",
            last_name="Admin",
        )
        changed = False
        if not user.is_super_admin:
            user.is_super_admin = True
            changed = True
        if not user.is_platform_admin:
            user.is_platform_admin = True
            changed = True
        if changed:
            user.save(update_fields=["is_super_admin", "is_platform_admin"])
        detach_user_from_all_cabinets(user)
        return user

    def _ensure_user(self, *, email: str, first_name: str, last_name: str) -> Any:
        user, _created = User.objects.get_or_create(
            email=email,
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "is_active": True,
            },
        )
        user.set_password(DEMO_PASSWORD)
        user.first_name = first_name
        user.last_name = last_name
        user.is_active = True
        user.save()
        return user

    def _ensure_cabinet(self, owner: Any) -> Any:
        membership = (
            Membership.objects.filter(user=owner, role=Role.CAIMAN)
            .select_related("cabinet")
            .first()
        )
        if membership:
            cabinet = membership.cabinet
            changed: list[str] = []
            if cabinet.name != DEMO_CABINET_NAME:
                cabinet.name = DEMO_CABINET_NAME
                changed.append("name")
            if cabinet.legal_name != DEMO_CABINET_LEGAL_NAME:
                cabinet.legal_name = DEMO_CABINET_LEGAL_NAME
                changed.append("legal_name")
            if changed:
                cabinet.save(update_fields=[*changed, "updated_at"])
                self.stdout.write(self.style.SUCCESS(f"Cabinet renommé : {cabinet.name}"))
            else:
                self.stdout.write(f"Cabinet existant réutilisé : {cabinet.name}")
            return cabinet
        cabinet, _membership = create_cabinet_with_owner(
            owner=owner,
            name=DEMO_CABINET_NAME,
            legal_name=DEMO_CABINET_LEGAL_NAME,
            siret="89012345600017",
            bar_association="Barreau de Paris",
            address_line1="24 rue de Rivoli",
            postal_code="75004",
            city="Paris",
        )
        self.stdout.write(self.style.SUCCESS(f"Cabinet créé : {cabinet.name}"))
        return cabinet

    def _ensure_practice_areas(self, cabinet: Any, kinshasa: list[Any], owner: Any) -> None:
        from django.core.exceptions import ValidationError

        from apps.tenants.legal_areas import ensure_default_legal_practice_areas
        from apps.tenants.models import LegalPracticeArea
        from apps.tenants.services import add_cabinet_practice_area

        ensure_default_legal_practice_areas()
        ileo_names = (
            "Droit du travail",
            "Droit de la famille",
            "Droit commercial",
        )
        assignments: list[tuple[Any, Any, tuple[str, ...]]] = [(cabinet, owner, ileo_names)]
        for spec, item in zip(KINSHASA_CABINETS, kinshasa, strict=True):
            member = (
                Membership.objects.filter(cabinet=item, role=Role.CAIMAN, is_active=True)
                .select_related("user")
                .first()
            )
            actor = member.user if member else owner
            assignments.append((item, actor, tuple(spec.get("specialties") or ())))
        for target, actor, names in assignments:
            for name in names:
                area = LegalPracticeArea.objects.filter(name=name).first()
                if area is None:
                    continue
                try:
                    add_cabinet_practice_area(
                        actor=actor,
                        cabinet=target,
                        practice_area=area,
                    )
                except ValidationError:
                    continue
        self.stdout.write(self.style.SUCCESS("Spécialités des cabinets enregistrées."))

    def _ensure_kinshasa_cabinets(self, ministry: Any) -> list[Any]:
        """Cinq cabinets du Barreau de Kinshasa/Gombe pour la supervision."""
        from apps.procurations.services import stamp_granted_procuration

        created: list[Any] = []
        for spec in KINSHASA_CABINETS:
            owner = self._ensure_user(
                email=spec["owner_email"],
                first_name=spec["owner_first_name"],
                last_name=spec["owner_last_name"],
            )
            cabinet = Cabinet.objects.filter(name=spec["name"]).first()
            fields = {
                "legal_name": spec["legal_name"],
                "bar_association": spec["bar_association"],
                "address_line1": spec["address_line1"],
                "address_line2": spec.get("address_line2") or "",
                "city": "Kinshasa",
                "country": "CD",
            }
            if cabinet is None:
                cabinet, _membership = create_cabinet_with_owner(
                    owner=owner,
                    name=spec["name"],
                    **fields,
                )
                self.stdout.write(self.style.SUCCESS(f"Cabinet Kinshasa créé : {cabinet.name}"))
            else:
                Membership.objects.get_or_create(
                    cabinet=cabinet,
                    user=owner,
                    defaults={
                        "role": Role.CAIMAN,
                        "is_active": True,
                        "created_by": owner,
                    },
                )
                changed = [key for key, value in fields.items() if getattr(cabinet, key) != value]
                if changed:
                    for key in changed:
                        setattr(cabinet, key, fields[key])
                    cabinet.save(update_fields=[*changed, "updated_at"])
            created.append(cabinet)

            with cabinet_context(cabinet):
                client = Client.objects.filter(
                    cabinet=cabinet,
                    last_name=spec["client_last_name"],
                    first_name=spec["client_first_name"],
                ).first()
                if client is None:
                    client = create_client(
                        cabinet=cabinet,
                        user=owner,
                        client_type=ClientType.PERSON,
                        first_name=spec["client_first_name"],
                        last_name=spec["client_last_name"],
                        city="Kinshasa",
                        country="CD",
                    )
                matter = Matter.objects.filter(
                    cabinet=cabinet,
                    title=spec["matter_title"],
                ).first()
                if matter is None:
                    matter = create_matter(
                        user=ministry,
                        title=spec["matter_title"],
                        jurisdiction=spec["jurisdiction"],
                        scale=spec.get("scale") or MatterScale.NATIONAL,
                        practice_area=(spec.get("specialties") or ("",))[0],
                    )
                stamp_granted_procuration(
                    matter=matter,
                    cabinet=cabinet,
                    actor=ministry,
                    purpose="Représentation et actes de procédure",
                    ministry_reference=f"MJ/GS/2026/{cabinet.slug[:8].upper()}",
                )
        return created

    def _ensure_team(self, cabinet: Any, owner: Any) -> dict[str, Any]:
        users: dict[str, Any] = {Role.CAIMAN: owner}
        for member in TEAM:
            user = self._ensure_user(
                email=member["email"],
                first_name=member["first_name"],
                last_name=member["last_name"],
            )
            Membership.objects.get_or_create(
                cabinet=cabinet,
                user=user,
                defaults={
                    "role": member["role"],
                    "is_active": True,
                    "created_by": owner,
                },
            )
            users[member["role"]] = user
        return users

    def _ensure_clients(self, cabinet: Any, owner: Any) -> dict[str, Client]:
        by_key: dict[str, Client] = {}
        for data in PERSONS:
            client = Client.objects.filter(cabinet=cabinet, email=data["email"]).first()
            if client is None:
                client = create_client(
                    cabinet=cabinet,
                    user=owner,
                    client_type=ClientType.PERSON,
                    country="FR",
                    **data,
                )
            by_key[data["email"]] = client
        for data in COMPANIES:
            client = Client.objects.filter(cabinet=cabinet, email=data["email"]).first()
            if client is None:
                client = create_client(
                    cabinet=cabinet,
                    user=owner,
                    client_type=ClientType.COMPANY,
                    country="FR",
                    **data,
                )
            by_key[data["email"]] = client
        self.stdout.write(f"Clients : {len(by_key)}")
        return by_key

    def _ensure_matters(
        self,
        cabinet: Any,
        owner: Any,
        lawyer: Any,
        associate: Any,
        clients: dict[str, Client],
        ministry: Any,
    ) -> dict[str, Matter]:
        from apps.procurations.services import stamp_granted_procuration

        specs: list[dict[str, Any]] = [
            {
                "title": "Licenciement contesté",
                "client": clients["julie.martin@example.com"],
                "lawyer": lawyer,
                "practice_area": "Droit du travail",
                "jurisdiction": "Tribunal du travail de la Gombe",
                "scale": MatterScale.NATIONAL,
                "opposing_party": "SAS Horizon RH",
                "status": MatterStatus.IN_PROGRESS,
                "description": "Contestation d'un licenciement pour faute.",
                "notes": "Pièces RH à relancer.",
            },
            {
                "title": "Contentieux commercial",
                "client": clients["contact@technova.example"],
                "lawyer": owner,
                "practice_area": "Droit commercial",
                "jurisdiction": "Tribunal de commerce de la Gombe",
                "scale": MatterScale.NATIONAL,
                "opposing_party": "LogiParts SARL",
                "status": MatterStatus.OPEN,
                "description": "Litige fournisseur / client B2B. Factures impayées.",
            },
            {
                "title": "Divorce par consentement mutuel",
                "client": clients["sophie.leroux@example.com"],
                "lawyer": lawyer,
                "practice_area": "Droit de la famille",
                "jurisdiction": "Tribunal de paix de Kinshasa/Gombe",
                "scale": MatterScale.NATIONAL,
                "opposing_party": "Thomas Leroux",
                "status": MatterStatus.IN_PROGRESS,
                "description": "Convention de divorce, résidence des enfants.",
            },
            {
                "title": "Servitude de passage",
                "client": clients["etienne.moreau@example.com"],
                "lawyer": associate,
                "practice_area": "Droit immobilier",
                "jurisdiction": "Tribunal de grande instance de Kinshasa/Gombe",
                "scale": MatterScale.NATIONAL,
                "opposing_party": "Famille Charpentier",
                "status": MatterStatus.ON_HOLD,
                "description": "Expertise géomètre en attente.",
            },
            {
                "title": "Titre de séjour — renouvellement",
                "client": clients["ines.diallo@example.com"],
                "lawyer": associate,
                "practice_area": "Droit des étrangers",
                "jurisdiction": "Conseil d'État",
                "scale": MatterScale.NATIONAL,
                "status": MatterStatus.OPEN,
                "description": "Recours gracieux puis contentieux si besoin.",
            },
            {
                "title": "Accident de la circulation",
                "client": clients["paul.girard@example.com"],
                "lawyer": lawyer,
                "practice_area": "Droit du préjudice corporel",
                "jurisdiction": "Tribunal de grande instance de Kinshasa/Kalamu",
                "scale": MatterScale.NATIONAL,
                "opposing_party": "Assureur AXA",
                "status": MatterStatus.IN_PROGRESS,
                "description": "Expertise médicale contradictoire.",
            },
            {
                "title": "Succession Rousseau",
                "client": clients["claire.rousseau@example.com"],
                "lawyer": owner,
                "practice_area": "Droit des successions",
                "jurisdiction": "Tribunal de paix de Kinshasa/Ngaliema",
                "scale": MatterScale.NATIONAL,
                "status": MatterStatus.CLOSED,
                "description": "Partage amiable clôturé.",
                "closed_at": timezone.localdate() - timedelta(days=20),
            },
            {
                "title": "Impayés de loyer commercial",
                "client": clients["hugo.petit@example.com"],
                "lawyer": lawyer,
                "practice_area": "Droit des baux commerciaux",
                "jurisdiction": "Tribunal de commerce de la Gombe",
                "scale": MatterScale.NATIONAL,
                "opposing_party": "SARL Café du Nord",
                "status": MatterStatus.IN_PROGRESS,
                "description": "Commandement de payer, clause résolutoire.",
            },
            {
                "title": "Concurrence déloyale",
                "client": clients["juridique@atelier-lumiere.example"],
                "lawyer": owner,
                "practice_area": "Propriété intellectuelle",
                "jurisdiction": "Tribunal de grande instance de Kinshasa/Gombe",
                "scale": MatterScale.NATIONAL,
                "opposing_party": "Studio Halo",
                "status": MatterStatus.OPEN,
                "description": "Imitation de marque et détournement de clientèle.",
            },
            {
                "title": "Contrat-cadre transport",
                "client": clients["direction@nord-logistique.example"],
                "lawyer": associate,
                "practice_area": "Droit des contrats",
                "jurisdiction": "Tribunal de commerce de la Gombe",
                "scale": MatterScale.NATIONAL,
                "status": MatterStatus.OPEN,
                "description": "Négociation et relecture du contrat-cadre 2026.",
            },
            {
                "title": "Licenciement économique",
                "client": clients["karim.benali@example.com"],
                "lawyer": lawyer,
                "practice_area": "Droit du travail",
                "jurisdiction": "Tribunal du travail de la Gombe",
                "scale": MatterScale.NATIONAL,
                "opposing_party": "Industrie Métal SAS",
                "status": MatterStatus.ON_HOLD,
                "description": "Attente de l'ordonnance de conciliation.",
            },
            {
                "title": "Assemblée générale SCI",
                "client": clients["gerance@maison-bellevue.example"],
                "lawyer": owner,
                "practice_area": "Droit des sociétés",
                "jurisdiction": "Tribunal de commerce de la Gombe",
                "scale": MatterScale.NATIONAL,
                "status": MatterStatus.CLOSED,
                "description": "PV d'AG et cession de parts.",
                "closed_at": timezone.localdate() - timedelta(days=45),
            },
            {
                "title": "Coopération judiciaire — CPI",
                "client": clients["contact@technova.example"],
                "lawyer": owner,
                "practice_area": "Droit pénal international",
                "jurisdiction": "Cour pénale internationale",
                "scale": MatterScale.INTERNATIONAL,
                "opposing_party": "Procureur de la CPI",
                "status": MatterStatus.IN_PROGRESS,
                "description": "Demande d'entraide et d'exécution d'un mandat d'arrêt.",
                "notes": "Traité à l'échelle internationale par le Ministère de la Justice.",
            },
            {
                "title": "Différend commercial OHADA",
                "client": clients["direction@nord-logistique.example"],
                "lawyer": lawyer,
                "practice_area": "Droit OHADA",
                "jurisdiction": "Cour commune de justice et d'arbitrage (OHADA)",
                "scale": MatterScale.INTERNATIONAL,
                "opposing_party": "Transit Afrique SA",
                "status": MatterStatus.OPEN,
                "description": "Pourvoi et arbitrage devant la CCJA.",
            },
        ]
        matters: dict[str, Matter] = {}
        for spec in specs:
            existing = Matter.unscoped.filter(
                cabinet=cabinet,
                title=spec["title"],
            ).first()
            if existing:
                existing.scale = spec.get("scale", MatterScale.NATIONAL)
                existing.jurisdiction = spec.get("jurisdiction", existing.jurisdiction)
                existing.save(update_fields=["scale", "jurisdiction", "updated_at"])
                stamp_granted_procuration(matter=existing, cabinet=cabinet, actor=ministry)
                matters[spec["title"]] = existing
                continue
            closed_at = spec.pop("closed_at", None)
            status = spec.pop("status")
            spec.pop("client", None)
            spec.pop("lawyer", None)
            matter = create_matter(
                user=ministry,
                **spec,
            )
            stamp_granted_procuration(matter=matter, cabinet=cabinet, actor=ministry)
            if status != MatterStatus.OPEN or closed_at:
                update_matter(
                    matter=matter,
                    user=ministry,
                    status=status,
                    closed_at=closed_at,
                )
            matters[matter.title] = matter
        self.stdout.write(f"Dossiers : {len(matters)}")
        return matters

    def _ensure_events(
        self,
        cabinet: Any,
        owner: Any,
        lawyer: Any,
        associate: Any,
        matters: dict[str, Matter],
    ) -> None:
        now = timezone.now()
        specs: list[dict[str, Any]] = [
            {
                "title": "Audience prud'homale",
                "matter": matters["Licenciement contesté"],
                "event_type": EventType.HEARING,
                "starts_at": now + timedelta(days=3, hours=2),
                "location": "Tribunal du travail de la Gombe",
                "assigned_to": lawyer,
                "remind_at": now + timedelta(days=2),
            },
            {
                "title": "Préparer conclusions",
                "matter": matters["Licenciement contesté"],
                "event_type": EventType.TASK,
                "starts_at": now + timedelta(days=1),
                "assigned_to": associate,
            },
            {
                "title": "RDV cliente Julie Martin",
                "matter": matters["Licenciement contesté"],
                "event_type": EventType.APPOINTMENT,
                "starts_at": now + timedelta(days=5, hours=4),
                "ends_at": now + timedelta(days=5, hours=5),
                "location": "Cabinet — salle 2",
                "assigned_to": lawyer,
            },
            {
                "title": "Délai conclusions adverse",
                "matter": matters["Contentieux commercial"],
                "event_type": EventType.DEADLINE,
                "starts_at": now + timedelta(days=12),
                "all_day": True,
                "assigned_to": owner,
            },
            {
                "title": "Expertise médicale",
                "matter": matters["Accident de la circulation"],
                "event_type": EventType.APPOINTMENT,
                "starts_at": now + timedelta(days=8, hours=3),
                "location": "Cabinet du Dr. Morel, Nantes",
                "assigned_to": lawyer,
            },
            {
                "title": "Relancer la préfecture",
                "matter": matters["Titre de séjour — renouvellement"],
                "event_type": EventType.TASK,
                "starts_at": now + timedelta(hours=20),
                "assigned_to": associate,
            },
            {
                "title": "Audience référé loyers",
                "matter": matters["Impayés de loyer commercial"],
                "event_type": EventType.HEARING,
                "starts_at": now + timedelta(days=15, hours=1),
                "location": "TJ de Lille",
                "assigned_to": lawyer,
            },
            {
                "title": "Relire contrat-cadre",
                "matter": matters["Contrat-cadre transport"],
                "event_type": EventType.TASK,
                "starts_at": now - timedelta(days=2),
                "assigned_to": associate,
                "is_done": True,
            },
            {
                "title": "Mise en demeure Studio Halo",
                "matter": matters["Concurrence déloyale"],
                "event_type": EventType.DEADLINE,
                "starts_at": now + timedelta(days=6),
                "assigned_to": owner,
            },
            {
                "title": "Point équipe dossiers ouverts",
                "matter": None,
                "event_type": EventType.REMINDER,
                "starts_at": now + timedelta(days=2, hours=9),
                "location": "Visio interne",
                "assigned_to": owner,
            },
        ]
        created = 0
        for spec in specs:
            is_done = spec.pop("is_done", False)
            existing = Event.objects.filter(
                cabinet=cabinet,
                title=spec["title"],
                matter=spec["matter"],
            ).first()
            if existing:
                continue
            event = create_event(cabinet=cabinet, user=owner, **spec)
            if is_done:
                event.is_done = True
                event.save(update_fields=["is_done", "updated_at"])
            created += 1
        self.stdout.write(f"Événements ajoutés : {created}")

    def _ensure_time_and_expenses(
        self,
        cabinet: Any,
        owner: Any,
        lawyer: Any,
        associate: Any,
        matters: dict[str, Matter],
    ) -> None:
        from apps.billing.models import Expense, TimeEntry

        time_specs: list[dict[str, Any]] = [
            {
                "matter": matters["Licenciement contesté"],
                "user": lawyer,
                "description": "Consultation initiale",
                "duration_minutes": 90,
                "hourly_rate": Decimal("280.00"),
            },
            {
                "matter": matters["Licenciement contesté"],
                "user": associate,
                "description": "Rédaction conclusions",
                "duration_minutes": 180,
                "hourly_rate": Decimal("180.00"),
            },
            {
                "matter": matters["Contentieux commercial"],
                "user": owner,
                "description": "Analyse du contrat-cadre et factures",
                "duration_minutes": 120,
                "hourly_rate": Decimal("320.00"),
            },
            {
                "matter": matters["Divorce par consentement mutuel"],
                "user": lawyer,
                "description": "Entretien et projet de convention",
                "duration_minutes": 75,
                "hourly_rate": Decimal("250.00"),
            },
            {
                "matter": matters["Accident de la circulation"],
                "user": lawyer,
                "description": "Étude du dossier médical",
                "duration_minutes": 60,
                "hourly_rate": Decimal("250.00"),
            },
            {
                "matter": matters["Impayés de loyer commercial"],
                "user": associate,
                "description": "Commandement de payer",
                "duration_minutes": 45,
                "hourly_rate": Decimal("180.00"),
            },
            {
                "matter": matters["Concurrence déloyale"],
                "user": owner,
                "description": "Recherche d'antériorités et constats",
                "duration_minutes": 150,
                "hourly_rate": Decimal("320.00"),
            },
            {
                "matter": matters["Succession Rousseau"],
                "user": owner,
                "description": "Clôture et envoi du décompte",
                "duration_minutes": 40,
                "hourly_rate": Decimal("280.00"),
            },
        ]
        added_time = 0
        for spec in time_specs:
            if TimeEntry.objects.filter(
                cabinet=cabinet,
                matter=spec["matter"],
                description=spec["description"],
            ).exists():
                continue
            create_time_entry(cabinet=cabinet, **spec)
            added_time += 1

        expense_specs: list[dict[str, Any]] = [
            {
                "matter": matters["Licenciement contesté"],
                "description": "Frais d'huissier — signification",
                "amount": Decimal("86.40"),
                "incurred_on": timezone.localdate() - timedelta(days=12),
            },
            {
                "matter": matters["Contentieux commercial"],
                "description": "Greffe tribunal de commerce",
                "amount": Decimal("142.00"),
                "incurred_on": timezone.localdate() - timedelta(days=5),
            },
            {
                "matter": matters["Accident de la circulation"],
                "description": "Honoraires expert médical",
                "amount": Decimal("450.00"),
                "incurred_on": timezone.localdate() - timedelta(days=8),
            },
            {
                "matter": matters["Concurrence déloyale"],
                "description": "Constat d'huissier — site web concurrent",
                "amount": Decimal("320.00"),
                "incurred_on": timezone.localdate() - timedelta(days=3),
            },
        ]
        added_exp = 0
        for spec in expense_specs:
            if Expense.objects.filter(
                cabinet=cabinet,
                matter=spec["matter"],
                description=spec["description"],
            ).exists():
                continue
            create_expense(cabinet=cabinet, user=owner, **spec)
            added_exp += 1
        self.stdout.write(f"Temps ajoutés : {added_time} · Débours ajoutés : {added_exp}")

    def _ensure_invoices(
        self,
        cabinet: Any,
        owner: Any,
        matters: dict[str, Matter],
    ) -> None:
        from apps.billing.models import Expense, Invoice, TimeEntry

        plans: list[dict[str, Any]] = [
            {
                "matter": matters["Succession Rousseau"],
                "status": InvoiceStatus.PAID,
                "notes": "Solde succession — réglé par virement.",
                "issued_ago": 40,
                "due_ago": 10,
            },
            {
                "matter": matters["Licenciement contesté"],
                "status": InvoiceStatus.SENT,
                "notes": "Provision honoraires + débours huissier.",
                "issued_ago": 7,
                "due_ago": -23,
            },
            {
                "matter": matters["Contentieux commercial"],
                "status": InvoiceStatus.OVERDUE,
                "notes": "Relance J+15 à envoyer.",
                "issued_ago": 45,
                "due_ago": 15,
            },
            {
                "matter": matters["Divorce par consentement mutuel"],
                "status": InvoiceStatus.DRAFT,
                "notes": "Brouillon à valider avec la cliente.",
                "issued_ago": 0,
                "due_ago": -30,
            },
        ]
        created = 0
        for plan in plans:
            matter = plan["matter"]
            if Invoice.objects.filter(cabinet=cabinet, matter=matter).exists():
                continue
            time_ids = list(
                TimeEntry.objects.filter(
                    cabinet=cabinet,
                    matter=matter,
                    invoice__isnull=True,
                    is_billable=True,
                ).values_list("pk", flat=True)
            )
            expense_ids = list(
                Expense.objects.filter(
                    cabinet=cabinet,
                    matter=matter,
                    invoice__isnull=True,
                    is_billable=True,
                ).values_list("pk", flat=True)
            )
            if not time_ids and not expense_ids:
                continue
            invoice = create_draft_invoice(
                cabinet=cabinet,
                user=owner,
                client=matter.client,
                matter=matter,
                time_entry_ids=[str(pk) for pk in time_ids],
                expense_ids=[str(pk) for pk in expense_ids],
                notes=plan["notes"],
            )
            if plan["status"] != InvoiceStatus.DRAFT:
                self._issue_without_pdf(
                    invoice=invoice,
                    user=owner,
                    status=plan["status"],
                    issued_ago=plan["issued_ago"],
                    due_ago=plan["due_ago"],
                )
            created += 1
        self.stdout.write(f"Factures ajoutées : {created}")

    def _issue_without_pdf(
        self,
        *,
        invoice: Any,
        user: Any,
        status: str,
        issued_ago: int,
        due_ago: int,
    ) -> None:
        """Émet une facture sans appeler Celery / WeasyPrint."""
        with transaction.atomic():
            invoice.number = allocate_invoice_number(cabinet=invoice.cabinet)
            invoice.status = InvoiceStatus.SENT
            invoice.issued_at = timezone.localdate() - timedelta(days=issued_ago)
            invoice.due_at = timezone.localdate() - timedelta(days=due_ago)
            invoice.save(
                update_fields=["number", "status", "issued_at", "due_at", "updated_at"]
            )
        invoice.refresh_from_db()
        if status == InvoiceStatus.PAID:
            mark_invoice_paid(invoice=invoice, user=user)
        elif status == InvoiceStatus.OVERDUE:
            mark_invoice_overdue(invoice=invoice, user=user)
        store_invoice_pdf(invoice=invoice, pdf_bytes=render_invoice_pdf_bytes(invoice))

    def _ensure_documents(
        self,
        cabinet: Any,
        owner: Any,
        matters: dict[str, Matter],
    ) -> None:
        specs = [
            (
                matters["Licenciement contesté"],
                "Lettre de licenciement",
                "correspondance, rh",
                "Madame, Monsieur,\nVeuillez trouver ci-joint la lettre de licenciement.\n",
            ),
            (
                matters["Contentieux commercial"],
                "Contrat-cadre 2024",
                "contrat, pièce",
                "Contrat-cadre de fourniture — version consolidée pour le contentieux.\n",
            ),
            (
                matters["Divorce par consentement mutuel"],
                "Projet de convention de divorce",
                "famille, projet",
                "Projet de convention à faire relire par la cliente avant dépôt.\n",
            ),
        ]
        created = 0
        for matter, title, tags, body in specs:
            if Document.objects.filter(cabinet=cabinet, matter=matter, title=title).exists():
                continue
            payload = BytesIO(body.encode("utf-8"))
            create_document_with_file(
                cabinet=cabinet,
                matter=matter,
                user=owner,
                title=title,
                uploaded_file=payload,
                filename=f"{title.lower().replace(' ', '_')}.txt",
                content_type="text/plain",
                description="Document de démonstration généré par seed_demo.",
                tags=[tag.strip() for tag in tags.split(",")],
            )
            created += 1
        self.stdout.write(f"Documents ajoutés : {created}")

    def _ensure_invitation(self, cabinet: Any, owner: Any) -> None:
        email = "stagiaire@example.com"
        if Invitation.objects.filter(
            cabinet=cabinet,
            email=email,
            accepted_at__isnull=True,
            is_deleted=False,
        ).exists():
            return
        invite_member(
            cabinet=cabinet,
            email=email,
            role=Role.LAWYER,
            invited_by=owner,
        )
        self.stdout.write("Invitation en attente : stagiaire@example.com")
