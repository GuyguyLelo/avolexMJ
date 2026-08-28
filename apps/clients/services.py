"""Services clients : CRUD, recherche, soft-delete."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.postgres.search import SearchVector
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils.translation import gettext_lazy as _

from apps.clients.models import Client, ClientType
from apps.tenants.roles import PERM_ADD, PERM_CHANGE, PERM_DELETE, PERM_VIEW
from apps.tenants.services import is_platform_admin, require_cabinet_perm

if TYPE_CHECKING:
    from apps.accounts.models import User
    from apps.tenants.models import Cabinet


def clients_queryset(*, cabinet: Cabinet, q: str = "") -> QuerySet[Client]:
    """Liste filtrée des clients du cabinet."""
    qs = Client.objects.filter(cabinet=cabinet).order_by("-updated_at")
    q = (q or "").strip()
    if not q:
        return qs
    return qs.filter(
        Q(first_name__icontains=q)
        | Q(last_name__icontains=q)
        | Q(company_name__icontains=q)
        | Q(email__icontains=q)
        | Q(phone__icontains=q)
        | Q(city__icontains=q)
    )


def refresh_client_search_vector(client: Client) -> None:
    """Met à jour le vecteur FTS PostgreSQL."""
    Client.objects.filter(pk=client.pk).update(
        search_vector=(
            SearchVector("first_name", weight="A", config="french")
            + SearchVector("last_name", weight="A", config="french")
            + SearchVector("company_name", weight="A", config="french")
            + SearchVector("email", weight="B", config="french")
            + SearchVector("phone", weight="C", config="french")
            + SearchVector("city", weight="C", config="french")
        )
    )


def _validate_client_identity(*, client_type: str, data: dict[str, Any]) -> None:
    if client_type == ClientType.COMPANY:
        if not (data.get("company_name") or "").strip():
            raise ValidationError({"company_name": _("La raison sociale est obligatoire.")})
    else:
        if not (data.get("last_name") or "").strip():
            raise ValidationError({"last_name": _("Le nom est obligatoire.")})


@transaction.atomic
def create_client(*, cabinet: Cabinet, user: User, **fields: Any) -> Client:
    """Crée un client pour le cabinet courant."""
    if not is_platform_admin(user):
        require_cabinet_perm(user=user, cabinet=cabinet, perm=PERM_ADD)
    client_type = fields.get("client_type") or ClientType.PERSON
    _validate_client_identity(client_type=client_type, data=fields)
    client = Client.objects.create(cabinet=cabinet, created_by=user, **fields)
    refresh_client_search_vector(client)
    return client


@transaction.atomic
def update_client(*, client: Client, user: User, **fields: Any) -> Client:
    """Met à jour un client."""
    require_cabinet_perm(user=user, cabinet=client.cabinet, perm=PERM_CHANGE)
    client_type = fields.get("client_type", client.client_type)
    merged = {
        "company_name": fields.get("company_name", client.company_name),
        "last_name": fields.get("last_name", client.last_name),
        "first_name": fields.get("first_name", client.first_name),
    }
    _validate_client_identity(client_type=client_type, data=merged)
    for key, value in fields.items():
        setattr(client, key, value)
    client.save()
    refresh_client_search_vector(client)
    return client


@transaction.atomic
def soft_delete_client(*, client: Client, user: User) -> None:
    """Suppression logique — refusée s'il reste des dossiers actifs."""
    require_cabinet_perm(user=user, cabinet=client.cabinet, perm=PERM_DELETE)
    if client.matters.filter(is_deleted=False).exists():
        raise ValidationError(
            _("Impossible de supprimer un client qui a encore des dossiers.")
        )
    client.soft_delete()


def get_client(*, cabinet: Cabinet, user: User, pk: str) -> Client:
    """Récupère un client du cabinet (permission view)."""
    require_cabinet_perm(user=user, cabinet=cabinet, perm=PERM_VIEW)
    return Client.objects.select_related("cabinet").get(pk=pk, cabinet=cabinet)
