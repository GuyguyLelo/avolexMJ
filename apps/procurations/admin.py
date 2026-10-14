"""Admin des procurations."""

from __future__ import annotations

from django.contrib import admin

from apps.procurations.models import Procuration, ProcurationSequence


@admin.register(Procuration)
class ProcurationAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Administration des procurations."""

    list_display = (
        "reference",
        "subject",
        "matter",
        "status",
        "ministry_reference",
        "cabinet",
        "conseiller_at",
        "granted_at",
        "expires_at",
    )
    list_filter = ("status", "scale")
    search_fields = ("reference", "ministry_reference", "purpose", "subject", "client_name")
    raw_id_fields = ("cabinet", "matter", "conseiller_by", "granted_by", "created_by")


@admin.register(ProcurationSequence)
class ProcurationSequenceAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Administration des séquences de référence."""

    list_display = ("cabinet", "year", "last_number")
    raw_id_fields = ("cabinet", "created_by")
