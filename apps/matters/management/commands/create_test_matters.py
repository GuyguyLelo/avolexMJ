"""Commande pour créer 4 dossiers de test."""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.matters.models import Matter, MatterParty, PartyRole
from apps.matters.services import allocate_matter_reference, refresh_matter_search_vector
from apps.tenants.models import Cabinet, Membership


class Command(BaseCommand):
    help = "Crée 4 dossiers de test avec des parties"

    def handle(self, *args, **options):
        self.stdout.write("Creation de 4 dossiers de test...")

        # Récupérer le premier cabinet et l'avocat responsable
        cabinet = Cabinet.objects.first()
        if not cabinet:
            self.stdout.write(self.style.ERROR("Aucun cabinet trouvé. Créez d'abord un cabinet."))
            return

        # Récupérer le premier avocat du cabinet
        membership = Membership.objects.filter(cabinet=cabinet).first()
        if not membership:
            self.stdout.write(self.style.ERROR("Aucun membre trouvé dans le cabinet."))
            return

        lawyer = membership.user

        # Créer 4 dossiers avec différents scénarios
        test_data = [
            {
                "title": "Affaire Ministère de la Justice vs Société XYZ",
                "description": "Litige contractuel entre le Ministère de la Justice et une société privée",
                "practice_area": "Droit des contrats",
                "jurisdiction": "Tribunal de Grande Instance de Kinshasa",
                "scale": "national",
                "parties": [
                    {"name": "Ministère de la Justice et Garde des Sceaux", "role": PartyRole.PLAINTIFF, "is_state_entity": True, "notes": "Service de l'État congolais"},
                    {"name": "Société XYZ S.A.", "role": PartyRole.DEFENDANT, "is_state_entity": False, "notes": "Société commerciale"},
                ],
            },
            {
                "title": "Affaire Jean-Michel K. vs Entreprise ABC",
                "description": "Litige de travail entre un employé et son employeur",
                "practice_area": "Droit du travail",
                "jurisdiction": "Tribunal du Travail de Kinshasa",
                "scale": "national",
                "parties": [
                    {"name": "Jean-Michel K.", "role": PartyRole.PLAINTIFF, "is_state_entity": False, "notes": "Employé"},
                    {"name": "Entreprise ABC Sarl", "role": PartyRole.DEFENDANT, "is_state_entity": False, "notes": "Employeur"},
                    {"name": "Marie L.", "role": PartyRole.WITNESS, "is_state_entity": False, "notes": "Collègue de travail"},
                ],
            },
            {
                "title": "Affaire République Démocratique du Congo vs Entreprise Minière",
                "description": "Litige fiscal avec une entreprise minière internationale",
                "practice_area": "Droit fiscal",
                "jurisdiction": "Cour Internationale d'Arbitrage",
                "scale": "international",
                "parties": [
                    {"name": "République Démocratique du Congo", "role": PartyRole.PLAINTIFF, "is_state_entity": True, "notes": "État congolais"},
                    {"name": "Entreprise Minière International Ltd", "role": PartyRole.DEFENDANT, "is_state_entity": False, "notes": "Société étrangère"},
                    {"name": "Ministère des Finances", "role": PartyRole.THIRD_PARTY, "is_state_entity": True, "notes": "Partie intéressée"},
                ],
            },
            {
                "title": "Affaire Succession Mbembo",
                "description": "Litige successoral entre héritiers",
                "practice_area": "Droit civil",
                "jurisdiction": "Tribunal de Paix de Lingwala",
                "scale": "national",
                "parties": [
                    {"name": "François Mbembo", "role": PartyRole.PLAINTIFF, "is_state_entity": False, "notes": "Héritier principal"},
                    {"name": "Marie Mbembo", "role": PartyRole.DEFENDANT, "is_state_entity": False, "notes": "Héritière"},
                    {"name": "Pierre Mbembo", "role": PartyRole.DEFENDANT, "is_state_entity": False, "notes": "Héritier"},
                    {"name": "Notaire Dupont", "role": PartyRole.WITNESS, "is_state_entity": False, "notes": "Rédacteur du testament"},
                ],
            },
        ]

        created_count = 0
        for i, data in enumerate(test_data, 1):
            with transaction.atomic():
                # Créer le dossier avec une référence unique
                import uuid
                ref_suffix = str(uuid.uuid4())[:8].upper()
                reference = f"DOS-2026-TEST-{ref_suffix}"

                matter = Matter.objects.create(
                    cabinet=cabinet,
                    created_by=lawyer,
                    responsible_lawyer=lawyer,
                    reference=reference,
                    title=data["title"],
                    description=data["description"],
                    practice_area=data["practice_area"],
                    jurisdiction=data["jurisdiction"],
                    scale=data["scale"],
                    status="open",
                    opened_at=timezone.localdate(),
                )

                # Mettre à jour le vecteur de recherche
                refresh_matter_search_vector(matter)

                # Créer les parties
                for party_data in data["parties"]:
                    MatterParty.objects.create(
                        cabinet=cabinet,
                        matter=matter,
                        name=party_data["name"],
                        role=party_data["role"],
                        is_state_entity=party_data["is_state_entity"],
                        notes=party_data["notes"],
                        created_by=lawyer,
                    )

            created_count += 1
            self.stdout.write(
                self.style.SUCCESS(f"[OK] Dossier {i} cree : {matter.reference} - {matter.title}")
            )

        self.stdout.write(
            self.style.SUCCESS(f"\n{created_count} dossiers de test crees avec succes !")
        )
