"""Context processors globaux."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.http import HttpRequest


def site_meta(request: HttpRequest) -> dict[str, Any]:
    """Expose le nom du site et des métadonnées UI aux templates."""
    return {
        "SITE_NAME": getattr(settings, "SITE_NAME", "AvoLex"),
        "SITE_COUNTRY": getattr(settings, "SITE_COUNTRY", "République Démocratique du Congo"),
        "SITE_INSTITUTION": getattr(
            settings, "SITE_INSTITUTION", "Ministère de la Justice et Garde des Sceaux"
        ),
        "SITE_AUTHORITY": getattr(settings, "SITE_AUTHORITY", "Le Gouvernement"),
        "DEFAULT_CURRENCY": getattr(settings, "DEFAULT_CURRENCY", "USD"),
        "STATIC_VERSION": getattr(settings, "STATIC_VERSION", "1"),
    }
