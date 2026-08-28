"""Configuration de l'application procurations."""

from __future__ import annotations

from django.apps import AppConfig


class ProcurationsConfig(AppConfig):
    """AppConfig pour apps.procurations."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.procurations"
    label = "procurations"
    verbose_name = "Procurations"
