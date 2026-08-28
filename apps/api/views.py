"""ViewSets REST filtrés par cabinet."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet
from rest_framework import viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.filters import SearchFilter
from rest_framework.pagination import PageNumberPagination

from apps.api.permissions import IsCabinetMember
from apps.api.serializers import ClientSerializer, EventSerializer, MatterSerializer
from apps.calendar_app.models import Event
from apps.clients.models import Client
from apps.clients.services import create_client, soft_delete_client, update_client
from apps.matters.models import Matter
from apps.matters.services import create_matter, soft_delete_matter, update_matter


class StandardPagination(PageNumberPagination):
    """Pagination API (20 / page)."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class CabinetModelViewSet(viewsets.ModelViewSet):
    """ViewSet de base : auth session + isolation cabinet."""

    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsCabinetMember,)
    pagination_class = StandardPagination
    filter_backends = (SearchFilter,)


class ClientViewSet(CabinetModelViewSet):
    """CRUD clients via API."""

    serializer_class = ClientSerializer
    search_fields = ("first_name", "last_name", "company_name", "email", "phone", "city")

    def get_queryset(self) -> QuerySet[Client]:
        return Client.objects.filter(cabinet=self.request.cabinet).order_by("-updated_at")  # type: ignore[attr-defined]

    def perform_create(self, serializer: ClientSerializer) -> None:
        client = create_client(
            cabinet=self.request.cabinet,  # type: ignore[attr-defined]
            user=self.request.user,  # type: ignore[arg-type]
            **serializer.validated_data,
        )
        serializer.instance = client

    def perform_update(self, serializer: ClientSerializer) -> None:
        client = update_client(
            client=serializer.instance,
            user=self.request.user,  # type: ignore[arg-type]
            **serializer.validated_data,
        )
        serializer.instance = client

    def perform_destroy(self, instance: Client) -> None:
        soft_delete_client(client=instance, user=self.request.user)  # type: ignore[arg-type]


class MatterViewSet(CabinetModelViewSet):
    """CRUD dossiers via API."""

    serializer_class = MatterSerializer
    search_fields = ("reference", "title", "practice_area", "jurisdiction", "client__last_name", "client__company_name")

    def get_queryset(self) -> QuerySet[Matter]:
        from apps.matters.services import matters_queryset

        return matters_queryset(
            cabinet=self.request.cabinet,  # type: ignore[attr-defined]
            user=self.request.user,  # type: ignore[arg-type]
            status=self.request.query_params.get("status") or "",
            scale=self.request.query_params.get("scale") or "",
        )

    def perform_create(self, serializer: MatterSerializer) -> None:
        data: dict[str, Any] = dict(serializer.validated_data)
        matter = create_matter(
            cabinet=self.request.cabinet,  # type: ignore[attr-defined]
            user=self.request.user,  # type: ignore[arg-type]
            client=data.pop("client"),
            title=data.pop("title"),
            responsible_lawyer=data.pop("responsible_lawyer", self.request.user),
            **data,
        )
        serializer.instance = matter

    def perform_update(self, serializer: MatterSerializer) -> None:
        matter = update_matter(
            matter=serializer.instance,
            user=self.request.user,  # type: ignore[arg-type]
            **serializer.validated_data,
        )
        serializer.instance = matter

    def perform_destroy(self, instance: Matter) -> None:
        soft_delete_matter(matter=instance, user=self.request.user)  # type: ignore[arg-type]


class EventViewSet(CabinetModelViewSet):
    """Liste / CRUD événements."""

    serializer_class = EventSerializer
    search_fields = ("title", "location")
    http_method_names = ("get", "post", "put", "patch", "delete", "head", "options")

    def get_queryset(self) -> QuerySet[Event]:
        return Event.objects.filter(cabinet=self.request.cabinet).order_by("starts_at")  # type: ignore[attr-defined]

    def perform_create(self, serializer: EventSerializer) -> None:
        from apps.calendar_app.services import create_event

        data = dict(serializer.validated_data)
        event = create_event(
            cabinet=self.request.cabinet,  # type: ignore[attr-defined]
            user=self.request.user,  # type: ignore[arg-type]
            title=data.pop("title"),
            starts_at=data.pop("starts_at"),
            **data,
        )
        serializer.instance = event

    def perform_update(self, serializer: EventSerializer) -> None:
        from apps.calendar_app.services import update_event

        event = update_event(
            event=serializer.instance,
            user=self.request.user,  # type: ignore[arg-type]
            **serializer.validated_data,
        )
        serializer.instance = event

    def perform_destroy(self, instance: Event) -> None:
        from apps.calendar_app.services import soft_delete_event

        soft_delete_event(event=instance, user=self.request.user)  # type: ignore[arg-type]
