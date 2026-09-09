"""Vues transverses (landing, healthcheck, home, supervision)."""

from __future__ import annotations

from typing import Any

from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views import View
from django.views.generic import TemplateView

from apps.core.dashboard import (
    build_cabinet_charts,
    build_dashboard_stats,
    build_platform_charts,
    build_platform_stats,
    recent_matters,
    recent_platform_activity,
    upcoming_events,
    upcoming_hearings,
    upcoming_platform_hearings,
)
from apps.core.mixins import BreadcrumbMixin
from apps.tenants.mixins import CabinetRequiredMixin, PlatformAdminRequiredMixin
from apps.tenants.services import is_platform_admin


class LandingView(TemplateView):
    """Page marketing publique. Les utilisateurs déjà connectés vont à l'app."""

    template_name = "core/landing.html"

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Évite de redemander une connexion si la session est déjà active."""
        if request.user.is_authenticated:
            if is_platform_admin(request.user):  # type: ignore[arg-type]
                return redirect("core:supervision")
            return redirect("core:home")
        return super().dispatch(request, *args, **kwargs)


class HomeView(CabinetRequiredMixin, BreadcrumbMixin, TemplateView):
    """Tableau de bord avec KPIs."""

    template_name = "core/home.html"

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Les comptes ministère vont à la supervision (pas de cabinet courant)."""
        if request.user.is_authenticated and is_platform_admin(request.user):  # type: ignore[arg-type]
            return redirect("core:supervision")
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumb(self) -> list[dict[str, str]]:
        """Pas de fil d'Ariane : le bandeau du dashboard suffit."""
        return []

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Ajoute les statistiques du cabinet courant."""
        ctx = super().get_context_data(**kwargs)
        cabinet = self.request.cabinet  # type: ignore[attr-defined]
        ctx["stats"] = build_dashboard_stats(cabinet=cabinet, user=self.request.user)
        ctx["cabinet_charts"] = build_cabinet_charts(cabinet=cabinet)
        ctx["recent_matters"] = recent_matters(cabinet=cabinet, user=self.request.user)
        ctx["upcoming_events"] = upcoming_events(cabinet=cabinet)
        ctx["upcoming_hearings"] = upcoming_hearings(cabinet=cabinet)
        return ctx


class SupervisionView(PlatformAdminRequiredMixin, BreadcrumbMixin, TemplateView):
    """Supervision cross-cabinet : activité de tous les cabinets."""

    template_name = "core/supervision.html"
    # Pas de cabinet requis : vue globale.
    cabinet_required = False

    def get_breadcrumb(self) -> list[dict[str, str]]:
        return [{"label": "Supervision"}]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["platform_stats"] = build_platform_stats()
        ctx["platform_charts"] = build_platform_charts()
        ctx["recent_activity"] = recent_platform_activity(limit=10)
        ctx["upcoming_hearings"] = upcoming_platform_hearings(limit=10)
        return ctx


class HealthCheckView(View):
    """Endpoint de santé pour reverse-proxy / monitoring."""

    http_method_names = ("get", "head")

    def get(self, request: HttpRequest) -> HttpResponse:
        """Vérifie la connexion PostgreSQL et renvoie un JSON de statut."""
        db_ok = False
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                db_ok = cursor.fetchone() is not None
        except Exception:
            db_ok = False

        status = 200 if db_ok else 503
        payload = {
            "status": "ok" if db_ok else "degraded",
            "database": "up" if db_ok else "down",
            "service": "avolex",
        }
        return JsonResponse(payload, status=status)
