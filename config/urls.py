"""URLconf racine AvoLex."""

from __future__ import annotations

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("cabinets/", include("apps.tenants.urls")),
    path("clients/", include("apps.clients.urls")),
    path("dossiers/", include("apps.matters.urls")),
    path("procurations/", include("apps.procurations.urls")),
    path("agenda/", include("apps.calendar_app.urls")),
    path("audiences/", include("apps.calendar_app.hearing_urls")),
    path("documents/", include("apps.documents.urls")),
    path("billing/", include("apps.billing.urls")),
    path("api/", include("apps.api.urls")),
]

if settings.DEBUG and "debug_toolbar" in settings.INSTALLED_APPS:
    import debug_toolbar  # type: ignore[import-untyped]

    urlpatterns = [
        path("__debug__/", include(debug_toolbar.urls)),
        *urlpatterns,
    ]
