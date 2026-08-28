"""Vues CRUD clients."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import QuerySet
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _g
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.clients.forms import ClientForm
from apps.clients.models import Client
from apps.clients.services import (
    clients_queryset,
    create_client,
    soft_delete_client,
    update_client,
)
from apps.core.mixins import BreadcrumbMixin
from apps.matters.models import Matter
from apps.tenants.mixins import CabinetPermissionMixin
from apps.tenants.roles import PERM_ADD, PERM_CHANGE, PERM_DELETE, PERM_VIEW
from apps.tenants.services import is_platform_admin


class ClientListView(CabinetPermissionMixin, BreadcrumbMixin, ListView):
    """Liste paginée + recherche."""

    template_name = "clients/client_list.html"
    context_object_name = "clients"
    paginate_by = 10
    required_perm = PERM_VIEW

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [{"label": _g("Clients")}]

    def get_queryset(self) -> QuerySet[Client]:
        return clients_queryset(
            cabinet=self.request.cabinet,  # type: ignore[attr-defined]
            q=self.request.GET.get("q", ""),
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["filter_q"] = self.request.GET.get("q", "")
        return ctx


class ClientDetailView(CabinetPermissionMixin, BreadcrumbMixin, DetailView):
    """Fiche client + historique des dossiers."""

    template_name = "clients/client_detail.html"
    context_object_name = "client"
    required_perm = PERM_VIEW

    def get_queryset(self) -> QuerySet[Client]:
        return Client.objects.all()

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Clients"), "url": reverse("clients:list")},
            {"label": str(self.object)},
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["matters"] = (
            Matter.objects.filter(client=self.object)
            .select_related("responsible_lawyer")
            .order_by("-opened_at", "-created_at")
        )
        if not is_platform_admin(self.request.user):  # type: ignore[arg-type]
            from apps.procurations.services import authorized_matter_ids_for_cabinet

            cabinet = self.request.cabinet  # type: ignore[attr-defined]
            ctx["matters"] = ctx["matters"].filter(
                pk__in=authorized_matter_ids_for_cabinet(cabinet=cabinet)
            )
        return ctx


class ClientCreateView(CabinetPermissionMixin, BreadcrumbMixin, CreateView):
    """Création client."""

    template_name = "clients/client_form.html"
    form_class = ClientForm
    required_perm = PERM_ADD
    platform_write = True

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Clients"), "url": reverse("clients:list")},
            {"label": _g("Nouveau client")},
        ]

    def form_valid(self, form: ClientForm) -> HttpResponse:
        try:
            client = create_client(
                cabinet=self.request.cabinet,  # type: ignore[attr-defined]
                user=self.request.user,  # type: ignore[arg-type]
                **form.cleaned_data,
            )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError) and hasattr(exc, "message_dict"):
                for field, errs in exc.message_dict.items():
                    for err in errs:
                        form.add_error(field if field != "__all__" else None, err)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Client créé."))
        return redirect("clients:detail", pk=client.pk)


class ClientUpdateView(CabinetPermissionMixin, BreadcrumbMixin, UpdateView):
    """Édition client."""

    template_name = "clients/client_form.html"
    form_class = ClientForm
    context_object_name = "client"
    required_perm = PERM_CHANGE

    def get_queryset(self) -> QuerySet[Client]:
        return Client.objects.all()

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [
            {"label": _g("Clients"), "url": reverse("clients:list")},
            {"label": str(self.object), "url": reverse("clients:detail", args=[self.object.pk])},
            {"label": _g("Modifier")},
        ]

    def form_valid(self, form: ClientForm) -> HttpResponse:
        try:
            update_client(
                client=self.object,
                user=self.request.user,  # type: ignore[arg-type]
                **form.cleaned_data,
            )
        except (ValidationError, PermissionDenied) as exc:
            if isinstance(exc, ValidationError) and hasattr(exc, "message_dict"):
                for field, errs in exc.message_dict.items():
                    for err in errs:
                        form.add_error(field if field != "__all__" else None, err)
                return self.form_invalid(form)
            messages.error(self.request, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, _g("Client mis à jour."))
        return redirect("clients:detail", pk=self.object.pk)


class ClientDeleteView(CabinetPermissionMixin, View):
    """Suppression logique."""

    required_perm = PERM_DELETE
    http_method_names = ("post",)

    def post(self, request: Any, pk: str) -> HttpResponse:
        client = get_object_or_404(Client, pk=pk)
        try:
            soft_delete_client(client=client, user=request.user)
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
            return redirect("clients:detail", pk=pk)
        messages.success(request, _g("Client supprimé."))
        return redirect("clients:list")
