"""Admin dossiers (UI métier complète à l'étape 5)."""

from __future__ import annotations

from django.contrib import admin

from apps.matters.models import Matter, MatterAction, MatterLawyer, MatterSequence


@admin.register(Matter)
class MatterAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Administration des dossiers."""

    list_display = ("reference", "title", "scale", "status", "cabinet", "updated_at")
    list_filter = ("scale", "status")
    search_fields = ("reference", "title", "opposing_party")
    raw_id_fields = ("cabinet", "responsible_lawyer", "created_by")


@admin.register(MatterLawyer)
class MatterLawyerAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Affectations avocats / dossiers."""

    list_display = ("matter", "lawyer", "is_lead", "assigned_at")
    list_filter = ("is_lead",)
    raw_id_fields = ("matter", "lawyer", "assigned_by")


@admin.register(MatterSequence)
class MatterSequenceAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Administration des séquences de référence."""

    list_display = ("cabinet", "year", "last_number")
    raw_id_fields = ("cabinet", "created_by")


@admin.register(MatterAction)
class MatterActionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Historique des actions dossier."""

    list_display = ("matter", "action", "actor", "created_at", "cabinet")
    list_filter = ("action",)
    raw_id_fields = ("cabinet", "matter", "actor", "created_by")
